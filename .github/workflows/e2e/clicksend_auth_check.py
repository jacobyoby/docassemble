"""ClickSend fax basic-auth check for docassemble#82 (H-12b).

Run inside the docassemble container venv after installing this branch's
fax/views.py, mirroring the other e2e *_check.py scripts:
    docker cp docassemble_webapp/docassemble/webapp/fax/views.py da:<site-packages>/docassemble/webapp/fax/views.py
    docker cp .github/workflows/e2e/clicksend_auth_check.py da:/tmp/clicksend_auth_check.py
    docker exec da <venv-python> /tmp/clicksend_auth_check.py

Forged ClickSend callbacks (missing/wrong basic-auth credentials) must get
403 and leave the stored fax record untouched; correctly authenticated
callbacks must be accepted and stored. Any configured api username/key pair
is accepted, since the send-side record carries no config name.
"""
import base64
import json

from flask import Flask

import docassemble.webapp.fax.views as fax_views

APP = Flask('clicksend_auth_check')
USERNAME = 'clicksend-user'
API_KEY = 'clicksend-key-abc123'
USERNAME_TWO = 'second-user'
API_KEY_TWO = 'second-key-xyz'
MESSAGE_ID = 'MSGTEST123'


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

    def get(self, key):
        return self.store.get(key)

    def pipeline(self):
        return FakePipe(self.store)


PARAMS = {
    'message_id': MESSAGE_ID,
    'status': 'delivered',
    'status_code': '200',
}


def basic_header(username, password):
    token = base64.b64encode((username + ':' + password).encode()).decode()
    return {'Authorization': 'Basic ' + token}


def good_config():
    return {'name': {
        'default': {'api username': USERNAME, 'api key': API_KEY},
        'other': {'api username': USERNAME_TWO, 'api key': API_KEY_TWO},
    }}


def run_callback(params, headers, config=None):
    fake_redis = FakeRedis()
    fake_redis.store['da:faxcallback:sid:' + MESSAGE_ID] = json.dumps({'message_id': MESSAGE_ID})
    fax_views.clicksend_config = config
    fax_views.fax_provider = 'clicksend'
    fax_views.r = fake_redis
    with APP.test_request_context('/fax/clicksend_fax_callback', method='POST', data=params, headers=headers):
        response = fax_views.clicksend_fax_callback()
    if isinstance(response, tuple):
        status = response[1]
    else:
        status = response.status_code
    return status, fake_redis.store


failures = []


def check(label, func):
    try:
        func()
    except Exception as err:
        failures.append(label)
        print("FAIL " + label + ": " + type(err).__name__ + " " + str(err)[:150])
    else:
        print("PASS " + label)


def stored_status(store):
    return json.loads(store['da:faxcallback:sid:' + MESSAGE_ID]).get('status')


def missing_auth_rejected():
    status, store = run_callback(dict(PARAMS), {}, config=good_config())
    assert status == 403, status
    assert stored_status(store) is None, store


def wrong_password_rejected():
    status, store = run_callback(dict(PARAMS), basic_header(USERNAME, 'wrong-key'), config=good_config())
    assert status == 403, status
    assert stored_status(store) is None, store


def unknown_user_rejected():
    status, store = run_callback(dict(PARAMS), basic_header('nobody', API_KEY), config=good_config())
    assert status == 403, status
    assert stored_status(store) is None, store


def valid_auth_accepted():
    status, store = run_callback(dict(PARAMS), basic_header(USERNAME, API_KEY), config=good_config())
    assert status == 204, status
    assert stored_status(store) == 'delivered', store


def second_config_accepted():
    status, store = run_callback(dict(PARAMS), basic_header(USERNAME_TWO, API_KEY_TWO), config=good_config())
    assert status == 204, status
    assert stored_status(store) == 'delivered', store


def disabled_ignored():
    status, store = run_callback(dict(PARAMS), basic_header(USERNAME, API_KEY), config=None)
    assert status == 204, status
    assert stored_status(store) is None, store


check("missing auth rejected", missing_auth_rejected)
check("wrong password rejected", wrong_password_rejected)
check("unknown user rejected", unknown_user_rejected)
check("valid auth accepted and stored", valid_auth_accepted)
check("second config pair accepted", second_config_accepted)
check("disabled provider ignored", disabled_ignored)

if failures:
    raise SystemExit("FAILURES: " + ", ".join(failures))
print("ALL PASS")
