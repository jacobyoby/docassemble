"""Run unchanged legacy assertions and export synthetic parser decisions only."""

import base64
import fnmatch
import hashlib
import io
import json
from pathlib import Path
import random
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import test_native_config as legacy


def main() -> None:
    cases = []

    def record(kind, original):
        def checked(data):
            item = {"kind": kind, "data": base64.b64encode(data).decode(), "accepted": False}
            cases.append(item)
            result = original(data)
            item["accepted"] = True
            return result
        return checked

    legacy.CHECK.validate_uwsgi = record("uwsgi", legacy.CHECK.validate_uwsgi)
    legacy.CHECK.validate_nginx_dump = record("nginx", legacy.CHECK.validate_nginx_dump)
    output = io.StringIO()
    result = unittest.TextTestRunner(stream=output).run(unittest.defaultTestLoader.loadTestsFromModule(legacy))
    if not result.wasSuccessful():
        raise RuntimeError(output.getvalue())

    rng = random.Random(81)
    globs = []
    alphabet = "abz-!]^[]Ω☃"
    for i in range(10000):
        pattern = "[" + "".join(rng.choice(alphabet) for _ in range(rng.randrange(1, 8))) + "]"
        if i % 3 == 0:
            pattern = rng.choice(("*", "?", "x")) + pattern + rng.choice(("*", "?", ""))
        name = "".join(rng.choice(alphabet + ".x\n") for _ in range(rng.randrange(0, 4)))
        globs.append({"pattern": pattern, "name": name, "accepted": fnmatch.fnmatchcase(name, pattern)})

    print(json.dumps({"source_sha256": hashlib.sha256(legacy.SCRIPT.read_bytes()).hexdigest(),
                      "legacy_tests": result.testsRun, "cases": cases, "globs": globs}))


if __name__ == "__main__":
    main()
