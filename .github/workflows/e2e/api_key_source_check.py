"""API-key source check for docassemble#41 (H-9).

Run inside the docassemble container venv after installing this branch's
api/helpers.py, mirroring the other e2e *_check.py scripts:
    docker cp docassemble_webapp/docassemble/webapp/api/helpers.py da:<site-packages>/docassemble/webapp/api/helpers.py
    docker exec da <venv-python> /tmp/api_key_source_check.py

The API key must never come from a cookie: cookies are ambient
credentials, so a cookie-sourced key would make every CSRF-exempt API
route forgery-prone. Header, query, and body keys must be known to the
caller and stay accepted.
"""
from flask import Flask, request

from docassemble.webapp.api.helpers import get_api_key

APP = Flask('api_key_source_check')

failures = []


def key_in_context(path='/api', method='GET', cookie=None, headers=None, data=None):
    environ = {}
    if cookie:
        environ['HTTP_COOKIE'] = cookie
    with APP.test_request_context(path, method=method, headers=headers, data=data, environ_overrides=environ):
        return get_api_key()


def check(label, func):
    try:
        func()
    except Exception as err:
        failures.append(label)
        print("FAIL " + label + ": " + type(err).__name__ + " " + str(err)[:150])
    else:
        print("PASS " + label)


def cookie_key_ignored():
    assert key_in_context(cookie='X-API-Key=SECRETCOOKIE') is None


def header_key_accepted():
    assert key_in_context(headers={'X-API-Key': 'SECRETHEADER'}) == 'SECRETHEADER'


def query_key_accepted():
    assert key_in_context(path='/api?key=SECRETQUERY') == 'SECRETQUERY'


def bearer_key_accepted():
    assert key_in_context(headers={'Authorization': 'Bearer SECRETBEARER'}) == 'SECRETBEARER'


def form_key_accepted():
    assert key_in_context(method='POST', data={'key': 'SECRETFORM'}) == 'SECRETFORM'


def no_key_returns_none():
    assert key_in_context() is None


check("cookie key ignored", cookie_key_ignored)
check("header key accepted", header_key_accepted)
check("query key accepted", query_key_accepted)
check("bearer key accepted", bearer_key_accepted)
check("form key accepted", form_key_accepted)
check("no key returns none", no_key_returns_none)

if failures:
    raise SystemExit("api_key_source_check FAILED: " + ", ".join(failures))
print("api_key_source_check: all checks passed")
