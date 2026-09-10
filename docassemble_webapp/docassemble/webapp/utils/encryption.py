import pickle
import codecs
import secrets
import types
from io import IOBase as FileType
from dateutil import tz
from Cryptodome.Cipher import AES
from docassemble.base.functions import pickleable_objects
from docassemble.webapp.utils.fixpickle import fix_pickle_obj, fix_pickle_dict

TypeType = type(type(None))
NoneType = type(None)

# AES-GCM envelope for new encryptions (#40). Layout before base64:
# MAGIC + nonce(12) + tag(16) + ciphertext. Legacy CBC payloads (iv +
# ciphertext, no magic) keep decrypting via the CBC fallback so stored
# data survives the migration. A magic match with a bad tag raises
# instead of falling back: tampered data must fail closed.
GCM_MAGIC = b'$GCM1$'
GCM_NONCE_LEN = 12
GCM_TAG_LEN = 16
# Base64 form of the magic, for recognizing new envelopes without
# decoding. A legacy payload starts with 16 ASCII letters (the old raw
# iv), so an exact 8-letter prefix match is possible with probability
# (1/52)^8; such a collision fails closed in GCM verification instead
# of misdecrypting.
_GCM_B64_PREFIX = codecs.encode(GCM_MAGIC, 'base64').decode('utf-8').strip()


def _gcm_encrypt(plaintext, secret):
    nonce = secrets.token_bytes(GCM_NONCE_LEN)
    cipher = AES.new(bytearray(secret, encoding='utf-8'), AES.MODE_GCM, nonce=nonce)
    ciphertext, tag = cipher.encrypt_and_digest(bytes(plaintext))
    return GCM_MAGIC + nonce + tag + ciphertext


def _gcm_decrypt_envelope(raw, secret):
    # Caller has already matched the envelope prefix. Verification
    # failure raises ValueError: tampered data fails closed, never
    # falls back to the legacy path.
    nonce = raw[len(GCM_MAGIC):len(GCM_MAGIC) + GCM_NONCE_LEN]
    tag = raw[len(GCM_MAGIC) + GCM_NONCE_LEN:len(GCM_MAGIC) + GCM_NONCE_LEN + GCM_TAG_LEN]
    ciphertext = raw[len(GCM_MAGIC) + GCM_NONCE_LEN + GCM_TAG_LEN:]
    cipher = AES.new(bytearray(secret, encoding='utf-8'), AES.MODE_GCM, nonce=nonce)
    return cipher.decrypt_and_verify(ciphertext, tag)


def _pad_base64(text):
    return text + '=' * (-len(text) % 4)

def pad(the_string):
    return the_string + bytearray((16 - len(the_string) % 16) * chr(16 - len(the_string) % 16), encoding='utf-8')


def unpad(the_string):
    if isinstance(the_string[-1], int):
        return the_string[0:-the_string[-1]]
    return the_string[0:-ord(the_string[-1])]


def encrypt_phrase(phrase, secret):
    if isinstance(phrase, str):
        phrase = bytearray(phrase, 'utf-8')
    return codecs.encode(_gcm_encrypt(phrase, secret), 'base64').decode('utf-8')


def pack_phrase(phrase):
    phrase = bytearray(phrase, encoding='utf-8')
    return codecs.encode(phrase, 'base64').decode('utf-8')


def decrypt_phrase(phrase_string, secret):
    if phrase_string.startswith(_GCM_B64_PREFIX):
        raw = codecs.decode(bytearray(_pad_base64(phrase_string), encoding='utf-8'), 'base64')
        return _gcm_decrypt_envelope(raw, secret).decode('utf-8')
    phrase_string = bytearray(phrase_string, encoding='utf-8')
    decrypter = AES.new(bytearray(secret, encoding='utf-8'), AES.MODE_CBC, phrase_string[:16])
    return unpad(decrypter.decrypt(codecs.decode(phrase_string[16:], 'base64'))).decode('utf-8')


def unpack_phrase(phrase_string):
    return codecs.decode(bytearray(phrase_string, encoding='utf-8'), 'base64').decode('utf-8')


def encrypt_dictionary(the_dict, secret):
    return codecs.encode(_gcm_encrypt(pickle.dumps(pickleable_objects(the_dict)), secret), 'base64').decode()


def pack_object(the_object):
    return codecs.encode(pickle.dumps(safe_pickle(the_object)), 'base64').decode()


def unpack_object(the_string):
    the_string = bytearray(the_string, encoding='utf-8')
    return fix_pickle_dict(codecs.decode(the_string, 'base64'))


def encrypt_object(obj, secret):
    return codecs.encode(_gcm_encrypt(pickle.dumps(safe_pickle(obj)), secret), 'base64').decode()


def decrypt_object(obj_string, secret):
    if obj_string.startswith(_GCM_B64_PREFIX):
        raw = codecs.decode(bytearray(_pad_base64(obj_string), encoding='utf-8'), 'base64')
        return fix_pickle_obj(_gcm_decrypt_envelope(raw, secret))
    obj_string = bytearray(obj_string, encoding='utf-8')
    decrypter = AES.new(bytearray(secret, encoding='utf-8'), AES.MODE_CBC, obj_string[:16])
    return fix_pickle_obj(unpad(decrypter.decrypt(codecs.decode(obj_string[16:], 'base64'))))


def safe_pickle(the_object):
    if isinstance(the_object, list):
        return [safe_pickle(x) for x in the_object]
    if isinstance(the_object, dict):
        new_dict = {}
        for key, value in the_object.items():
            new_dict[key] = safe_pickle(value)
        return new_dict
    if isinstance(the_object, set):
        new_set = set()
        for sub_object in the_object:
            new_set.add(safe_pickle(sub_object))
        return new_set
    if isinstance(the_object, (types.ModuleType, types.FunctionType, TypeType, types.BuiltinFunctionType, types.BuiltinMethodType, types.MethodType, FileType)):
        return None
    return the_object


def pack_dictionary(the_dict):
    retval = codecs.encode(pickle.dumps(pickleable_objects(the_dict)), 'base64').decode()
    return retval


def decrypt_dictionary(dict_string, secret):
    if dict_string.startswith(_GCM_B64_PREFIX):
        raw = codecs.decode(bytearray(_pad_base64(dict_string), encoding='utf-8'), 'base64')
        return fix_pickle_dict(_gcm_decrypt_envelope(raw, secret))
    dict_string = bytearray(dict_string, encoding='utf-8')
    decrypter = AES.new(bytearray(secret, encoding='utf-8'), AES.MODE_CBC, dict_string[:16])
    return fix_pickle_dict(unpad(decrypter.decrypt(codecs.decode(dict_string[16:], 'base64'))))


def unpack_dictionary(dict_string):
    dict_string = codecs.decode(bytearray(dict_string, encoding='utf-8'), 'base64')
    return fix_pickle_dict(dict_string)


def nice_date_from_utc(timestamp, timezone=tz.tzlocal()):
    return timestamp.replace(tzinfo=tz.tzutc()).astimezone(timezone).strftime('%x %X')
