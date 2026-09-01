import datetime
import subprocess
import tempfile
import os
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs7
from cryptography.x509.oid import NameOID
from docassemble.base import email_crypto

import email as email_mod
inner = email_crypto.build_inner_mime("hello body", "<p>hello html</p>", [("a.txt", "text/plain", b"attachment bytes")])
parsed = email_mod.message_from_bytes(inner)
payloads = [part.get_payload(decode=True) for part in parsed.walk() if not part.is_multipart()]
assert any(b"hello body" in (pl or b"") for pl in payloads), payloads
assert any(b"attachment bytes" in (pl or b"") for pl in payloads)

key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "recipient@example.com")])
now = datetime.datetime.now(datetime.timezone.utc)
cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
        .public_key(key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now).not_valid_after(now + datetime.timedelta(days=1))
        .sign(key, hashes.SHA256()))
pem = cert.public_bytes(serialization.Encoding.PEM).decode()

body, sealed = email_crypto.smime_encrypt(inner, [pem])
assert sealed[0][0] == "smime.p7m" and len(sealed[0][2]) > 500
decrypted = pkcs7.pkcs7_decrypt_der(sealed[0][2], cert, key, [])
assert decrypted == inner, "smime roundtrip mismatch"
print("PASS smime roundtrip (encrypt with cert, decrypt with key, bytes identical)")

try:
    email_crypto.smime_encrypt(inner, ["not a certificate"])
    print("FAIL bad cert accepted"); raise SystemExit(1)
except email_crypto.DAEmailCryptoError as err:
    print("PASS bad cert raises:", str(err)[:60])

with tempfile.TemporaryDirectory() as home:
    os.chmod(home, 0o700)
    subprocess.run(["gpg", "--homedir", home, "--batch", "--quiet", "--passphrase", "",
                    "--quick-generate-key", "pgptest@example.com", "rsa2048", "encrypt", "1d"],
                   check=True, capture_output=True)
    pub = subprocess.run(["gpg", "--homedir", home, "--armor", "--export", "pgptest@example.com"],
                         check=True, capture_output=True).stdout.decode()
    body, sealed = email_crypto.pgp_encrypt(inner, [pub])
    assert sealed[0][0] == "message.asc" and b"BEGIN PGP MESSAGE" in sealed[0][2]
    dec = subprocess.run(["gpg", "--homedir", home, "--batch", "--quiet", "--passphrase", "", "--decrypt"],
                         input=sealed[0][2], capture_output=True, check=True)
    assert dec.stdout == inner, "pgp roundtrip mismatch"
    print("PASS pgp roundtrip (encrypt with exported pubkey, decrypt with keyring, bytes identical)")

try:
    email_crypto.pgp_encrypt(inner, ["garbage key"])
    print("FAIL bad key accepted"); raise SystemExit(1)
except email_crypto.DAEmailCryptoError as err:
    print("PASS bad pgp key raises:", str(err)[:60])
