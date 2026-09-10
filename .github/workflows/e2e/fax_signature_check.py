"""Twilio fax signature check for docassemble#44 (H-12).

Run inside the docassemble container venv after installing this branch's
fax/views.py, mirroring the other e2e *_check.py scripts:
    docker cp docassemble_webapp/docassemble/webapp/fax/views.py da:<site-packages>/docassemble/webapp/fax/views.py
    docker exec da <venv-python> /tmp/fax_signature_check.py

Forged fax callbacks must get 403 and write nothing; a correctly
signed callback must be accepted and stored.
"""
from flask import Flask
from twilio.request_validator import RequestValidator

import docassemble.webapp.fax.views as fax_views

APP = Flask('fax_signature_check')
TOKEN = 'test-twilio-auth-token'
ACCOUNT_SID = 'ACtestaccountsid'


class FakePipe:
    def __init__(self, store):
        self.store = store

    def set(self, key, value):
        self.store[key] = value

    def expire(self, key, ttl):
        pass

    def execute(self):
        pass


class FakeRedis:
    def __init__(self):
        self.store = {}

    def pipeline(self):
        return FakePipe(self.store)


PARAMS = {
    'FaxSid': 'FXtestfaxsid',
    'AccountSid': ACCOUNT_SID,
    'From': '+15551234567',
    'To': '+15557654321',
    'FaxStatus': 'delivered',
}

failures = []


def run_callback(params, headers, config=None):
    fake_redis = FakeRedis()
    fax_views.twilio_config = config
    fax_views.r = fake_redis
    with APP.test_request_context('/fax/fax_callback', method='POST', data=params, headers=headers):
        response = fax_views.fax_callback()
    if isinstance(response, tuple):
        status = response[1]
    else:
        status = response.status_code
    return status, fake_redis.store


def signed_headers(params):
    validator = RequestValidator(TOKEN)
    url = 'http://localhost/fax/fax_callback'
    return {'X-Twilio-Signature': validator.compute_signature(url, params)}


def good_config():
    return {'name': {'default': {'account sid': ACCOUNT_SID, 'auth token': TOKEN, 'fax': True}}}


def check(label, func):
    try:
        func()
    except Exception as err:
        failures.append(label)
        print("FAIL " + label + ": " + type(err).__name__ + " " + str(err)[:150])
    else:
        print("PASS " + label)


def missing_signature_rejected():
    status, store = run_callback(dict(PARAMS), {}, config=good_config())
    assert status == 403, status
    assert store == {}, store


def tampered_param_rejected():
    headers = signed_headers(PARAMS)
    bad = dict(PARAMS, FaxStatus='failed')
    status, store = run_callback(bad, headers, config=good_config())
    assert status == 403, status
    assert store == {}, store


def wrong_token_rejected():
    validator = RequestValidator('wrong-token')
    url = 'http://localhost/fax/fax_callback'
    headers = {'X-Twilio-Signature': validator.compute_signature(url, PARAMS)}
    status, store = run_callback(dict(PARAMS), headers, config=good_config())
    assert status == 403, status
    assert store == {}, store


def valid_signature_accepted():
    status, store = run_callback(dict(PARAMS), signed_headers(PARAMS), config=good_config())
    assert status == 204, status
    assert 'da:faxcallback:sid:FXtestfaxsid' in store, store


def unknown_account_ignored():
    bad = dict(PARAMS, AccountSid='ACunknown')
    status, store = run_callback(bad, signed_headers(bad), config=good_config())
    assert status == 204, status
    assert store == {}, store


def disabled_provider_ignored():
    status, store = run_callback(dict(PARAMS), signed_headers(PARAMS), config=None)
    assert status == 204, status
    assert store == {}, store


check("missing signature rejected", missing_signature_rejected)
check("tampered param rejected", tampered_param_rejected)
check("wrong token rejected", wrong_token_rejected)
check("valid signature accepted", valid_signature_accepted)
check("unknown account ignored", unknown_account_ignored)
check("disabled provider ignored", disabled_provider_ignored)

if failures:
    raise SystemExit("fax_signature_check FAILED: " + ", ".join(failures))
print("fax_signature_check: all checks passed")
