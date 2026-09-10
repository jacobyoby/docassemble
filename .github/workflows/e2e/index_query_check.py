"""Structured index-query builder for docassemble#34 (C-11).

Run anywhere with the docassemble venv python, pointing at this branch's
index.py (copied next to this script as index_under_test.py by CI, or run
from the repo with docassemble_demo on sys.path):
    <venv-python> index_query_check.py

Proves filter/order input travels as bound parameters and raw SQL
fragments are rejected.
"""
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CANDIDATES = [
    os.path.join(HERE, "index_under_test.py"),
    "/Users/jacobrakai/Projects/docassemble/docassemble_demo/docassemble/demo/index.py",
]
SOURCE = next((p for p in CANDIDATES if os.path.isfile(p)), None)
if SOURCE is None:
    raise SystemExit("index_query_check: index.py under test not found")

spec = importlib.util.spec_from_file_location("index_under_test", SOURCE)
index_mod = importlib.util.module_from_spec(spec)
sys.modules["index_under_test"] = index_mod
spec.loader.exec_module(index_mod)
build_report_query = index_mod.build_report_query

failures = []


def check(label, func):
    try:
        func()
    except Exception as err:
        failures.append(label)
        print("FAIL " + label + ": " + type(err).__name__ + " " + str(err)[:130])
    else:
        print("PASS " + label)


def structured_filter_parameterized():
    query, params = build_report_query(
        "myindex",
        filter_by=[("start_time", ">", "2026-08-10T00:00:00")],
        order_by=("start_time", "DESC"),
    )
    assert query.count("%s") == 4, query
    assert params == ["myindex", "start_time", "2026-08-10T00:00:00", "start_time"], params
    assert "2026-08-10" not in query, query
    assert "DESC" in query and "TEMPLATE" not in query, query


def key_with_quote_parameterized():
    query, params = build_report_query("a'b\"c; DROP TABLE x; --")
    assert params == ["a'b\"c; DROP TABLE x; --"], params
    assert "DROP" not in query, query


def raw_string_filter_rejected():
    try:
        build_report_query("k", filter_by="(data->>'x')::date > 'today'")
    except ValueError:
        return
    raise AssertionError("raw SQL filter string accepted")


def operator_injection_rejected():
    try:
        build_report_query("k", filter_by=[("start_time", "> '1' OR '1'='1", "x")])
    except ValueError:
        return
    raise AssertionError("operator injection accepted")


def field_injection_rejected():
    for bad_field in ["start_time) OR ('1'='1", "data->>'start_time", "start_time; DROP TABLE jsonstorage; --"]:
        try:
            build_report_query("k", filter_by=[(bad_field, "=", "x")])
        except ValueError:
            continue
        raise AssertionError("field injection accepted: " + bad_field)


def order_direction_injection_rejected():
    try:
        build_report_query("k", order_by=("start_time", "DESC; DROP TABLE jsonstorage; --"))
    except ValueError:
        return
    raise AssertionError("order direction injection accepted")


def no_filter_no_order():
    query, params = build_report_query("k")
    assert query == "SELECT data FROM jsonstorage WHERE tags=%s", query
    assert params == ["k"], params


check("structured filter parameterized", structured_filter_parameterized)
check("key with quote parameterized", key_with_quote_parameterized)
check("raw string filter rejected", raw_string_filter_rejected)
check("operator injection rejected", operator_injection_rejected)
check("field injection rejected", field_injection_rejected)
check("order direction injection rejected", order_direction_injection_rejected)
check("no filter no order", no_filter_no_order)

if failures:
    raise SystemExit("index_query_check FAILED: " + ", ".join(failures))
print("index_query_check: all checks passed")
