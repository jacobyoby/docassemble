"""AES-GCM envelope check for docassemble#40 (H-8).

Run inside the docassemble container venv after installing this branch's
encryption.py, mirroring the other e2e *_check.py scripts:
    docker cp docassemble_webapp/docassemble/webapp/utils/encryption.py da:<site-packages>/docassemble/webapp/utils/encryption.py
    docker exec da <venv-python> /tmp/aes_gcm_check.py

New encryptions must use authenticated AES-GCM; legacy CBC payloads
must keep decrypting; tampered envelopes must raise, never fall back.
"""
import codecs
import string

from Cryptodome.Cipher import AES

from docassemble.webapp.utils.encryption import (
    encrypt_phrase,
    decrypt_phrase,
    encrypt_object,
    decrypt_object,
    encrypt_dictionary,
    decrypt_dictionary,
    _GCM_B64_PREFIX,
)

SECRET = '0123456789abcdef0123456789abcdef'


def legacy_cbc_encrypt(plaintext, secret):
    import random as mt
    iv = ''.join(mt.choice(string.ascii_letters) for _ in range(16))
    encrypter = AES.new(bytearray(secret, encoding='utf-8'), AES.MODE_CBC, bytearray(iv, 'utf-8'))
    pad_len = 16 - len(plaintext) % 16
    padded = plaintext + bytes([pad_len]) * pad_len
    return iv + codecs.encode(encrypter.encrypt(padded), 'base64').decode('utf-8')


failures = []


def check(label, func):
    try:
        func()
    except Exception as err:
        failures.append(label)
        print("FAIL " + label + ": " + type(err).__name__ + " " + str(err)[:150])
    else:
        print("PASS " + label)


def gcm_prefix_unambiguous():
    # The envelope prefix covers the full 6-byte magic (8 b64 chars, no
    # padding ambiguity). A legacy payload starts with 16 ASCII letters
    # (the old raw iv), so only an exact 8-letter match collides:
    # probability (1/52)^8, and a collision fails closed in GCM verify
    # rather than misdecrypting.
    assert len(_GCM_B64_PREFIX) == 8, _GCM_B64_PREFIX
    assert not legacy_cbc_encrypt(b'prefix probe', SECRET).startswith(_GCM_B64_PREFIX)


def phrase_roundtrip():
    token = encrypt_phrase('hello secret phrase', SECRET)
    assert token.startswith(_GCM_B64_PREFIX), token[:12]
    assert decrypt_phrase(token, SECRET) == 'hello secret phrase'


def object_roundtrip():
    token = encrypt_object({'a': [1, 2, {'b': 'c'}]}, SECRET)
    back = decrypt_object(token, SECRET)
    assert back == {'a': [1, 2, {'b': 'c'}]}, back


def dictionary_roundtrip():
    token = encrypt_dictionary({'_internal': {}, 'k': 'v'}, SECRET)
    back = decrypt_dictionary(token, SECRET)
    assert back['k'] == 'v', back


def legacy_phrase_still_decrypts():
    token = legacy_cbc_encrypt(b'old stored secret', SECRET)
    assert not token.startswith(_GCM_B64_PREFIX)
    assert decrypt_phrase(token, SECRET) == 'old stored secret'


def tampered_envelope_raises():
    token = encrypt_phrase('tamper me', SECRET)
    raw = bytearray(token, 'utf-8')
    raw[-4] = ord('A') if raw[-4] != ord('A') else ord('B')
    try:
        decrypt_phrase(raw.decode('utf-8'), SECRET)
    except ValueError:
        return
    raise AssertionError("tampered envelope decrypted without error")


def wrong_secret_raises():
    token = encrypt_phrase('wrong secret', SECRET)
    try:
        decrypt_phrase(token, 'fedcba9876543210fedcba9876543210')
    except ValueError:
        return
    raise AssertionError("wrong secret decrypted without error")


def stripped_padding_roundtrip():
    token = encrypt_phrase('padding stripped in urls', SECRET).rstrip('=')
    assert decrypt_phrase(token, SECRET) == 'padding stripped in urls'


check("gcm prefix unambiguous", gcm_prefix_unambiguous)
check("phrase roundtrip", phrase_roundtrip)
check("object roundtrip", object_roundtrip)
check("dictionary roundtrip", dictionary_roundtrip)
check("legacy phrase still decrypts", legacy_phrase_still_decrypts)
check("tampered envelope raises", tampered_envelope_raises)
check("wrong secret raises", wrong_secret_raises)
check("stripped padding roundtrip", stripped_padding_roundtrip)

if failures:
    raise SystemExit("aes_gcm_check FAILED: " + ", ".join(failures))
print("aes_gcm_check: all checks passed")
