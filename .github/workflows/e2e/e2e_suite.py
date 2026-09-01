#!/usr/bin/env python3
"""End-to-end suite for a running docassemble server, stdlib only.

Every test drives the real REST API over HTTP. Usage:

    e2e_suite.py <base_url> <api_key>

Exits nonzero on the first failing test and prints one line per test.
The interview docassemble.demo:data/questions/test_issue_981.yml must be
installed (a checkboxes question saving to `fruit`, then a mandatory
result screen rendering fruit.true_values()).
"""
import json
import sys
import urllib.error
import urllib.parse
import urllib.request

INTERVIEW = "docassemble.demo:data/questions/test_issue_981.yml"


class ApiError(Exception):
    def __init__(self, method, url, status, body):
        self.status = status
        super().__init__("%s %s -> HTTP %d: %s" % (method, url, status, body[:300]))


def call(base, key, method, path, params=None, body=None):
    url = base + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    data = None
    headers = {"X-API-Key": key}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode("utf-8")
            return resp.status, (json.loads(raw) if raw.strip() else None)
    except urllib.error.HTTPError as err:
        raise ApiError(method, url, err.code, err.read().decode("utf-8", "replace")) from err


def new_session(base, key):
    _, d = call(base, key, "GET", "/api/session/new", params={"i": INTERVIEW})
    return d["session"], d["secret"]


def get_question(base, key, session, secret):
    _, d = call(base, key, "GET", "/api/session/question",
                params={"i": INTERVIEW, "session": session, "secret": secret})
    return d


def set_variables(base, key, session, secret, variables, extra=None):
    payload = {"i": INTERVIEW, "session": session, "secret": secret, "variables": variables}
    if extra:
        payload.update(extra)
    return call(base, key, "POST", "/api/session", body=payload)


def test_auth_rejected(base, key):
    try:
        call(base, "wrong-key-000000000000000000000000", "GET", "/api/user")
    except ApiError as err:
        if err.status in (401, 403):
            return
        raise
    raise AssertionError("bogus API key was accepted")


def test_session_lifecycle(base, key):
    session, secret = new_session(base, key)
    q = get_question(base, key, session, secret)
    if q.get("questionText") != "Which fruits?":
        raise AssertionError("first question wrong: %r" % q.get("questionText"))
    call(base, key, "DELETE", "/api/session",
         params={"i": INTERVIEW, "session": session, "secret": secret})
    sessions_left = call(base, key, "GET", "/api/interviews",
                         params={"i": INTERVIEW})[1]
    for item in sessions_left.get("items", []):
        if item.get("session") == session:
            raise AssertionError("deleted session still listed")


def test_dadict_object_notation(base, key):
    """The documented way: send a real DADict via object notation."""
    session, secret = new_session(base, key)
    dadict = {"_class": "docassemble.base.core.DADict",
              "instanceName": "fruit",
              "auto_gather": False, "gathered": True,
              "elements": {"apple": True, "banana": False, "cherry": True}}
    set_variables(base, key, session, secret, {"fruit": dadict})
    q = get_question(base, key, session, secret)
    sub = q.get("subquestionText") or ""
    if "apple and cherry" not in sub:
        raise AssertionError("object notation did not gather: %r" % sub)


def test_plain_dict_converts(base, key):
    """This branch's fix: a plain all-bool dict becomes a gathered DADict."""
    session, secret = new_session(base, key)
    set_variables(base, key, session, secret,
                  {"fruit": {"apple": True, "banana": False, "cherry": True}})
    q = get_question(base, key, session, secret)
    sub = q.get("subquestionText") or ""
    if "apple and cherry" not in sub:
        raise AssertionError("plain dict was not converted: %r" % sub)


def test_scalar_roundtrip(base, key):
    session, secret = new_session(base, key)
    set_variables(base, key, session, secret,
                  {"note_text": "Núñez Peña", "note_count": 3, "note_flag": False})
    # GET /api/session returns the interview's variable store itself.
    _, v = call(base, key, "GET", "/api/session",
                params={"i": INTERVIEW, "session": session, "secret": secret})
    got = (v.get("note_text"), v.get("note_count"), v.get("note_flag"))
    if got != ("Núñez Peña", 3, False):
        raise AssertionError("scalar roundtrip mismatch: %r" % (got,))


def test_bool_dict_divergence(base, key):
    """KNOWN DIVERGENCE from upstream (see FORK.md and upstream PR #984).

    On this branch every non-empty all-bool plain dict converts to a
    DADict, including one meant as plain data. Upstream declined exactly
    this (their counterexample: payload = {'error': False}). This test
    pins the divergence so a rebase that silently drops the conversion is
    caught here, not in an interview.
    """
    session, secret = new_session(base, key)
    set_variables(base, key, session, secret, {"payload": {"error": False}})
    _, v = call(base, key, "GET", "/api/session",
                params={"i": INTERVIEW, "session": session, "secret": secret})
    payload = v.get("payload")
    # The read-back class is reported as docassemble.base.util.DADict
    # (an alias of the core class), so match on the class name, not the
    # module, to stay robust to that aliasing.
    if not (isinstance(payload, dict) and str(payload.get("_class", "")).endswith(".DADict")):
        raise AssertionError("divergence changed: payload was %r" % (payload,))


def test_back_action(base, key):
    session, secret = new_session(base, key)
    set_variables(base, key, session, secret,
                  {"fruit": {"apple": True, "banana": False, "cherry": True}})
    call(base, key, "POST", "/api/session/back",
         body={"i": INTERVIEW, "session": session, "secret": secret})
    q = get_question(base, key, session, secret)
    if q.get("questionText") != "Which fruits?":
        raise AssertionError("back did not return to the question: %r" % q.get("questionText"))


TESTS = [
    test_auth_rejected,
    test_session_lifecycle,
    test_dadict_object_notation,
    test_plain_dict_converts,
    test_scalar_roundtrip,
    test_bool_dict_divergence,
    test_back_action,
]


def main():
    base, key = sys.argv[1], sys.argv[2]
    failed = 0
    for test in TESTS:
        try:
            test(base, key)
            print("PASS  " + test.__name__)
        except Exception as err:  # noqa: BLE001 - report and continue
            failed += 1
            print("FAIL  %s: %s" % (test.__name__, err))
    print("%d/%d passed" % (len(TESTS) - failed, len(TESTS)))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
