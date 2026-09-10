"""AST guard check for docassemble#35 (H-1).

Run inside the docassemble container venv after installing this branch's
astparser.py, mirroring the other e2e *_check.py scripts:
    docker cp docassemble_base/docassemble/base/astparser.py da:<site-packages>/docassemble/base/astparser.py
    docker exec da <venv-python> /tmp/ast_guard_check.py

Dunder attribute chains must be illegal in both detectors while ordinary
variable references stay legal.
"""
import ast

from docassemble.base.astparser import DetectIllegal, DetectIllegalQuery

CASES = [
    (DetectIllegal, 'person.name', False),
    (DetectIllegal, 'plain_name', False),
    (DetectIllegal, 'a[b]', False),
    (DetectIllegal, 'x._private', False),
    (DetectIllegal, 'x.__class__', True),
    (DetectIllegal, 'x.__class__.__base__', True),
    (DetectIllegal, 'x.__dict__', True),
    (DetectIllegal, '__import__("os")', True),
    (DetectIllegalQuery, 'name', False),
    (DetectIllegalQuery, 'x.__class__', True),
    (DetectIllegalQuery, 'x.__subclasses__', True),
]

failures = []
for cls, expr, want_illegal in CASES:
    detector = cls()
    detector.visit(ast.parse(expr))
    if detector.illegal != want_illegal:
        failures.append(cls.__name__ + ':' + expr)
        print("FAIL %s %r: illegal=%s want=%s" % (cls.__name__, expr, detector.illegal, want_illegal))
    else:
        print("PASS %s %r" % (cls.__name__, expr))

if failures:
    raise SystemExit("ast_guard_check FAILED: " + ", ".join(failures))
print("ast_guard_check: all checks passed")
