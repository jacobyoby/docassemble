"""Keygen check for docassemble#50 (H-18).

Run inside the docassemble container venv after installing this branch's
generate_key.py, mirroring the other e2e *_check.py scripts:
    docker cp docassemble_base/docassemble/base/generate_key.py da:<site-packages>/docassemble/base/generate_key.py
    docker cp .github/workflows/e2e/keygen_check.py da:/tmp/keygen_check.py
    docker exec da <venv-python> /tmp/keygen_check.py

random_digits() backs phone and e-mail verification codes, so it must draw
from a CSPRNG (secrets), never the predictable random.random() PRNG.
"""
import string

from docassemble.base.generate_key import (
    random_alphanumeric,
    random_digits,
    random_lower_string,
    random_string,
)

failures = []


def check(label, func):
    try:
        func()
    except Exception as err:
        failures.append(label)
        print("FAIL " + label + ": " + type(err).__name__ + " " + str(err)[:150])
    else:
        print("PASS " + label)


def digits_shape():
    for length in (4, 6, 8):
        code = random_digits(length)
        assert isinstance(code, str), repr(code)
        assert len(code) == length, repr(code)
        assert all(char in string.digits for char in code), repr(code)


def digits_vary():
    assert len({random_digits(12) for _ in range(4)}) > 1


def digits_from_csprng():
    import docassemble.base.generate_key as keygen

    source = open(keygen.__file__, encoding="utf-8").read()
    assert "import secrets" in source, "secrets import missing"
    body = source.split("def random_digits", 1)[1].split("\ndef ", 1)[0]
    code = "\n".join(
        line.split("#", 1)[0] for line in body.splitlines()
    )
    assert "secrets." in code, "random_digits does not use secrets"
    assert "random.random()" not in code, "predictable PRNG still present"


def other_generators_unchanged():
    assert len(random_string(16)) == 16
    assert all(c in string.ascii_letters for c in random_string(64))
    assert len(random_lower_string(10)) == 10
    assert len(random_alphanumeric(20)) == 20
    assert all(c in string.ascii_uppercase + string.ascii_lowercase + string.digits for c in random_alphanumeric(64))


check("random_digits shape (length, all digits)", digits_shape)
check("random_digits varies across calls", digits_vary)
check("random_digits draws from secrets", digits_from_csprng)
check("other generators unchanged", other_generators_unchanged)

if failures:
    raise SystemExit("FAILURES: " + ", ".join(failures))
print("ALL PASS")
