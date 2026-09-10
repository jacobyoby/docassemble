import string
import random
import secrets
import sys

__all__ = ['random_string', 'random_alphanumeric']

r = random.SystemRandom()


def random_bytes(length):
    return bytearray(ord(r.choice(string.ascii_letters)) for i in range(length))


def random_lower_string(length):
    return ''.join(r.choice(string.ascii_lowercase) for i in range(length))


def random_string(length):
    return ''.join(r.choice(string.ascii_letters) for i in range(length))


def random_alphanumeric(length):
    return ''.join(r.choice(string.ascii_uppercase + string.ascii_lowercase + string.digits) for x in range(length))


def random_digits(num):
    # NB: secrets, not random.random(). random_digits() backs phone and e-mail
    # verification codes, so the digits must come from a CSPRNG. The rest of
    # this module already uses random.SystemRandom (os.urandom-backed); only
    # this function used the predictable Mersenne Twister global PRNG.
    length = int(num)
    return ''.join(secrets.choice(string.digits) for _ in range(length))

if __name__ == "__main__":
    sys.stdout.write(random_string(32))
