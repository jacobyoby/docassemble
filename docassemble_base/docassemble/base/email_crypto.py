"""Encrypt outgoing email for send_email() (issues #445 S/MIME, #288 PGP).

Both entry points take the fully assembled inner MIME message (body, HTML
alternative, and attachments) and return replacement (body_text, attachment
tuples) for the outer message, so every provider path that can carry an
attachment can carry the ciphertext. Both fail closed: a missing, empty, or
unparseable certificate or key raises DAEmailCryptoError before anything is
handed to a mail provider. There is no plaintext fallback.
"""
import email.encoders
import email.mime.application
import email.mime.multipart
import email.mime.text
import os
import subprocess
import tempfile

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.ciphers import algorithms
from cryptography.hazmat.primitives.serialization import pkcs7


class DAEmailCryptoError(Exception):
    pass


def build_inner_mime(body, html, attachments):
    """Assemble the plaintext message that will be encrypted.

    Args:
        body (str): Plain-text body.
        html (str or None): HTML alternative.
        attachments (list): Tuples of (filename, content_type, data_bytes).

    Returns:
        bytes: The serialized inner MIME message.
    """
    if html:
        content = email.mime.multipart.MIMEMultipart('alternative')
        content.attach(email.mime.text.MIMEText(body or '', 'plain', 'utf-8'))
        content.attach(email.mime.text.MIMEText(html, 'html', 'utf-8'))
    else:
        content = email.mime.text.MIMEText(body or '', 'plain', 'utf-8')
    if attachments:
        outer = email.mime.multipart.MIMEMultipart('mixed')
        outer.attach(content)
        for (filename, content_type, data) in attachments:
            maintype, _, subtype = (content_type or 'application/octet-stream').partition('/')
            part = email.mime.application.MIMEApplication(data, _subtype=subtype or 'octet-stream')
            part.replace_header('Content-Type', (content_type or 'application/octet-stream') + '; name="' + filename + '"')
            part.add_header('Content-Disposition', 'attachment', filename=filename)
            outer.attach(part)
        content = outer
    return content.as_bytes()


def load_certificates(cert_sources):
    """Parse recipient X.509 certificates, raising on anything unusable.

    Args:
        cert_sources (list): PEM strings, PEM bytes, or file paths.

    Returns:
        list: cryptography Certificate objects, one or more.
    """
    certs = []
    for source in cert_sources:
        data = _read_source(source, 'certificate')
        try:
            certs.append(x509.load_pem_x509_certificate(data))
        except ValueError as err:
            raise DAEmailCryptoError("Could not parse an S/MIME recipient certificate (expecting PEM): " + str(err)) from err
    if len(certs) == 0:
        raise DAEmailCryptoError("smime_encrypt_for was given but contained no certificates")
    return certs


def smime_encrypt(inner_mime_bytes, cert_sources):
    """Encrypt the inner message for the given certificates.

    Returns:
        tuple: (body_text, [(filename, content_type, ciphertext_bytes)]).
    """
    certs = load_certificates(cert_sources)
    builder = pkcs7.PKCS7EnvelopeBuilder().set_data(inner_mime_bytes).set_content_encryption_algorithm(algorithms.AES256)
    for cert in certs:
        builder = builder.add_recipient(cert)
    ciphertext = builder.encrypt(serialization.Encoding.DER, [pkcs7.PKCS7Options.Binary])
    return ("This is an S/MIME encrypted message.",
            [("smime.p7m", 'application/pkcs7-mime; smime-type=enveloped-data; name="smime.p7m"', ciphertext)])


def load_pgp_keys(key_sources, gnupg_home):
    """Import recipient public keys into a scratch keyring, fail-closed.

    Returns:
        list: Fingerprints of the imported keys.
    """
    fingerprints = []
    for source in key_sources:
        data = _read_source(source, 'PGP public key')
        with tempfile.NamedTemporaryFile(suffix='.asc', delete=False) as keyfile:
            keyfile.write(data)
            key_path = keyfile.name
        try:
            result = _gpg(gnupg_home, ['--import', key_path])
            if result.returncode != 0:
                raise DAEmailCryptoError("gpg could not import a recipient public key: " + result.stderr.decode('utf-8', 'replace').strip())
        finally:
            os.remove(key_path)
    listing = _gpg(gnupg_home, ['--list-keys', '--with-colons'])
    for line in listing.stdout.decode('utf-8', 'replace').splitlines():
        if line.startswith('fpr:'):
            fingerprints.append(line.split(':')[9])
    if len(fingerprints) == 0:
        raise DAEmailCryptoError("pgp_encrypt_for was given but no usable public keys were imported")
    return fingerprints


def pgp_encrypt(inner_mime_bytes, key_sources):
    """Encrypt the inner message for the given PGP public keys.

    Returns:
        tuple: (body_text, [(filename, content_type, armored_bytes)]).
    """
    with tempfile.TemporaryDirectory() as gnupg_home:
        os.chmod(gnupg_home, 0o700)
        fingerprints = load_pgp_keys(key_sources, gnupg_home)
        command = ['--armor', '--trust-model', 'always', '--encrypt']
        for fpr in fingerprints:
            command.extend(['--recipient', fpr])
        result = _gpg(gnupg_home, command, input_bytes=inner_mime_bytes)
        if result.returncode != 0 or not result.stdout:
            raise DAEmailCryptoError("gpg encryption failed: " + result.stderr.decode('utf-8', 'replace').strip())
        return ("This is a PGP encrypted message.",
                [("message.asc", 'application/pgp-encrypted; name="message.asc"', result.stdout)])


def _gpg(gnupg_home, args, input_bytes=None):
    return subprocess.run(
        ['gpg', '--homedir', gnupg_home, '--batch', '--no-tty', '--quiet'] + args,
        input=input_bytes, capture_output=True, check=False, timeout=60)


def _read_source(source, kind):
    if hasattr(source, 'path'):
        source = source.path()
    if isinstance(source, str):
        if '-----BEGIN' in source:
            return source.encode('utf-8')
        if os.path.isfile(source):
            with open(source, 'rb') as the_file:
                return the_file.read()
        raise DAEmailCryptoError("A " + kind + " was given as a string that is neither PEM/armored content nor an existing file path")
    if isinstance(source, bytes):
        return source
    raise DAEmailCryptoError("Could not read a " + kind + " from " + repr(type(source).__name__))
