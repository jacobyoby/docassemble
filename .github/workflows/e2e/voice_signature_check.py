"""Twilio voice signature check for docassemble#103 (H-12d).

Run inside the docassemble container venv after installing this branch's
monitor/views.py, mirroring the other e2e *_check.py scripts:
    docker cp docassemble_webapp/docassemble/webapp/monitor/views.py da:<site-packages>/docassemble/webapp/monitor/views.py
    docker cp .github/workflows/e2e/voice_signature_check.py da:/tmp/voice_signature_check.py
    docker exec da <venv-python> /tmp/voice_signature_check.py

A posted AccountSid is a non-secret identifier. Both voice webhooks must
validate the X-Twilio-Signature header (HMAC-SHA1 over the URL plus sorted
params, per Twilio's documented scheme) against the matching account's auth
token; failures get 403. Valid requests keep their existing TwiML behavior.
"""
import base64
import hashlib
import hmac

from flask import Flask

import docassemble.webapp.monitor.views as monitor_views
from docassemble.base.thread_context import empty_globals, global_context

APP = Flask('voice_signature_check')
APP.register_blueprint(monitor_views.monitor_bp)
ACCOUNT_SID = 'ACtestaccountsid123'
AUTH_TOKEN = 'test-auth-token-abc123'


class FakeRedis:
    def get(self, key):
        return None

    def delete(self, key):
        pass


def twilio_signature(url, params, token):
    data = url + ''.join(key + params[key] for key in sorted(params))
    digest = hmac.new(token.encode(), data.encode(), hashlib.sha1).digest()
    return base64.b64encode(digest).decode()


def good_config():
    return {'name': {'default': {'account sid': ACCOUNT_SID, 'auth token': AUTH_TOKEN, 'voice': True}}}


def run_endpoint(path, params, signature=None, config=None):
    monitor_views.twilio_config = config
    monitor_views.r = FakeRedis()
    headers = {}
    if signature is not None:
        headers['X-Twilio-Signature'] = signature
    with APP.test_request_context(path, method='POST', data=params, headers=headers):
        # Mirror production, which binds a thread context per request
        # (lifecycle.setup_variables); the views call set_language/word.
        with global_context(empty_globals()):
            if 'digits' in path:
                response = monitor_views.digits_endpoint()
            else:
                response = monitor_views.voice()
    if isinstance(response, tuple):
        return response[1], response[0]
    return response.status_code, response.get_data(as_text=True)


failures = []


def check(label, func):
    try:
        func()
    except Exception as err:
        failures.append(label)
        print("FAIL " + label + ": " + type(err).__name__ + " " + str(err)[:150])
    else:
        print("PASS " + label)


def valid_params(extra=None):
    params = {'AccountSid': ACCOUNT_SID, 'From': '+15551234567'}
    if extra:
        params.update(extra)
    return params


def computed_signature(path, params, token=AUTH_TOKEN):
    return twilio_signature('http://localhost' + path, params, token)


def missing_signature_rejected_digits():
    status, _ = run_endpoint('/monitor/digits', valid_params({'Digits': '12345'}), signature=None, config=good_config())
    assert status == 403, status


def wrong_signature_rejected_voice():
    status, _ = run_endpoint('/monitor/voice', valid_params(), signature='bogus', config=good_config())
    assert status == 403, status


def tampered_param_rejected_digits():
    params = valid_params({'Digits': '12345'})
    sig = computed_signature('/monitor/digits', params)
    evil = valid_params({'Digits': '99999'})
    status, _ = run_endpoint('/monitor/digits', evil, signature=sig, config=good_config())
    assert status == 403, status


def valid_digits_unknown_code_ok():
    params = valid_params({'Digits': '12345'})
    status, body = run_endpoint('/monitor/digits', params, signature=computed_signature('/monitor/digits', params), config=good_config())
    assert status == 200, status
    assert 'invalid or expired' in body, body[:150]


def valid_voice_gather_ok():
    params = valid_params()
    status, body = run_endpoint('/monitor/voice', params, signature=computed_signature('/monitor/voice', params), config=good_config())
    assert status == 200, status
    assert 'Gather' in body, body[:150]


def disabled_ignored():
    status, _ = run_endpoint('/monitor/voice', valid_params(), signature=None, config=None)
    assert status == 200, status


check("digits missing signature rejected", missing_signature_rejected_digits)
check("voice wrong signature rejected", wrong_signature_rejected_voice)
check("digits tampered param rejected", tampered_param_rejected_digits)
check("digits valid signature keeps TwiML", valid_digits_unknown_code_ok)
check("voice valid signature keeps gather", valid_voice_gather_ok)
check("disabled provider ignored", disabled_ignored)

if failures:
    raise SystemExit("FAILURES: " + ", ".join(failures))
print("ALL PASS")
