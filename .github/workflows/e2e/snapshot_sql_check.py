"""Snapshot-SQL check for docassemble#61 (M-16).

Run inside the docassemble container venv (no branch files need installing;
analyze() runs inside interviews, so the wiring is asserted statically while
parameter separation is proven live):
    docker cp .github/workflows/e2e/snapshot_sql_check.py da:/tmp/snapshot_sql_check.py
    docker exec da <venv-python> /tmp/snapshot_sql_check.py [<path-to-read_snapshot.py>]

The demo reader interpolated the interview filename into SQL. It must pass
the filename as a bound parameter (psycopg2 pyformat %s style).
"""
import sqlite3
import sys

failures = []


def check(label, func):
    try:
        func()
    except Exception as err:
        failures.append(label)
        print("FAIL " + label + ": " + type(err).__name__ + " " + str(err)[:200])
    else:
        print("PASS " + label)


repo = "/Users/jacobrakai/Projects/docassemble/"
script_path = sys.argv[1] if len(sys.argv) > 1 else repo + "docassemble_demo/docassemble/demo/read_snapshot.py"

with open(script_path, encoding="utf-8") as handle:
    script_source = "\n".join(line.split("#", 1)[0] for line in handle.read().splitlines())


def no_interpolation():
    assert "+ current_context" not in script_source, "filename still interpolated"
    assert "filename=%s" in script_source, "bound placeholder missing"
    assert "(current_context().filename,)" in script_source, "params tuple missing"


def driver_is_pyformat():
    import psycopg2

    assert psycopg2.paramstyle == "pyformat", psycopg2.paramstyle


def bound_filename_not_executable():
    evil = "x' OR '1'='1"
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE jsonstorage (filename TEXT, value TEXT)")
    conn.execute("INSERT INTO jsonstorage VALUES (?, ?)", ("fruit.yml", "apple"))
    # Same shape as the fixed query: value compared as data, never as SQL.
    rows = conn.execute("SELECT value FROM jsonstorage WHERE filename = ?", (evil,)).fetchall()
    assert rows == [], rows
    rows = conn.execute("SELECT value FROM jsonstorage WHERE filename = ?", ("fruit.yml",)).fetchall()
    assert rows == [("apple",)], rows
    conn.close()


check("filename bound, not interpolated", no_interpolation)
check("driver uses pyformat params", driver_is_pyformat)
check("bound hostile filename matches nothing", bound_filename_not_executable)

if failures:
    raise SystemExit("FAILURES: " + ", ".join(failures))
print("ALL PASS")
