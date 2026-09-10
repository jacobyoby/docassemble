"""Telnyx fax signature check for docassemble#83 (H-12c).

Run inside the docassemble container venv after installing this branch's
fax/views.py, mirroring the other e2e *_check.py scripts:
    docker cp docassemble_webapp/docassemble/webapp/fax/views.py da:<site-packages>/docassemble/webapp/fax/views.py
    docker cp .github/workflows/e2e/telnyx_signature_check.py da:/tmp/telnyx_signature_check.py
    docker exec da <venv-python> /tmp/telnyx_signature_check.py

Telnyx signs `{timestamp}|{raw body}` with Ed25519. Forged callbacks
(wrong key, tampered body, missing/stale headers) must get 403 and leave
the stored fax record untouched; correctly signed callbacks must be
accepted and stored. Test keys are generated in-process with the same
`cryptography` library the view uses.
"""
import base64
import json
import time

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from flask import Flask

import docassemble.webapp.fax.views as fax_views

APP = Flask('telnyx_signature_check')
FAX_ID = 'fax-test-id-123'
TOLERANCE = 300

PRIVATE_KEY = Ed25519PrivateKey.generate()
PUBLIC_B64 = base64.b64encode(PRIVATE_KEY.public_key().public_bytes_raw()).decode()
OTHER_KEY = Ed25519PrivateKey.generate()


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


def body_for(fax_id, status='delivered'):
    return json.dumps({
        'data': {
            'occurred_at': '2026-09-10T00:00:00Z',
            'payload': {'fax_id': fax_id, 'status': status, 'page_count': 3},
        },
    }).encode('utf-8')


def sign(raw, key, timestamp):
    return base64.b64encode(key.sign(str(timestamp).encode() + b'|' + raw)).decode()


def good_config():
    return {'name': {'default': {'public key': PUBLIC_B64}}}


def run_callback(raw, headers, config=None):
    fake_redis = FakeRedis()
    fake_redis.store['da:faxcallback:sid:' + FAX_ID] = json.dumps({'id': FAX_ID})
    fax_views.telnyx_config = config
    fax_views.r = fake_redis
    with APP.test_request_context('/fax/telnyx_fax_callback', method='POST', data=raw, content_type='application/json', headers=headers):
        response = fax_views.telnyx_fax_callback()
    if isinstance(response, tuple):
        status = response[1]
    else:
        status = response.status_code
    return status, fake_redis.store


def signed_headers(raw, key=None, timestamp=None):
    ts = int(time.time()) if timestamp is None else timestamp
    return {
        'telnyx-signature-ed25519': sign(raw, PRIVATE_KEY if key is None else key, ts),
        'telnyx-timestamp': str(ts),
    }


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
    return json.loads(store['da:faxcallback:sid:' + FAX_ID]).get('status')


def missing_headers_rejected():
    status, store = run_callback(body_for(FAX_ID), {}, config=good_config())
    assert status == 403, status
    assert stored_status(store) is None, store


def wrong_key_rejected():
    raw = body_for(FAX_ID)
    status, store = run_callback(raw, signed_headers(raw, key=OTHER_KEY), config=good_config())
    assert status == 403, status
    assert stored_status(store) is None, store


def tampered_body_rejected():
    raw = body_for(FAX_ID)
    headers = signed_headers(raw)
    evil = body_for(FAX_ID, status='failed')
    status, store = run_callback(evil, headers, config=good_config())
    assert status == 403, status
    assert stored_status(store) is None, store


def stale_timestamp_rejected():
    raw = body_for(FAX_ID)
    old = int(time.time()) - (TOLERANCE + 60)
    status, store = run_callback(raw, signed_headers(raw, timestamp=old), config=good_config())
    assert status == 403, status
    assert stored_status(store) is None, store


def valid_signature_accepted():
    raw = body_for(FAX_ID)
    status, store = run_callback(raw, signed_headers(raw), config=good_config())
    assert status == 204, status
    assert stored_status(store) == 'delivered', store


def unknown_fax_id_ignored():
    raw = body_for('no-such-fax')
    status, store = run_callback(raw, signed_headers(raw), config=good_config())
    assert status == 204, status
    assert stored_status(store) is None, store


def disabled_ignored():
    raw = body_for(FAX_ID)
    status, store = run_callback(raw, signed_headers(raw), config=None)
    assert status == 204, status
    assert stored_status(store) is None, store


check("missing headers rejected", missing_headers_rejected)
check("wrong key rejected", wrong_key_rejected)
check("tampered body rejected", tampered_body_rejected)
check("stale timestamp rejected", stale_timestamp_rejected)
check("valid signature accepted and stored", valid_signature_accepted)
check("unknown fax id ignored", unknown_fax_id_ignored)
check("disabled provider ignored", disabled_ignored)

if failures:
    raise SystemExit("FAILURES: " + ", ".join(failures))
print("ALL PASS")
