#!/usr/bin/env python3.14
"""Synthetic runtime command for exercising the actual mail shell/Go boundary."""
import hashlib
import os
from pathlib import Path
import sys

assert sys.argv[1:] == ['-m', 'docassemble.webapp.process_email', '/dev/stdin']
with open('/dev/stdin', 'rb') as stream:
    message = stream.read()
assert hashlib.sha256(message).hexdigest() == os.environ['SYNTHETIC_MAIL_SHA256']
mode = os.environ.get('SYNTHETIC_MAIL_MODE', 'input')
if mode != 'input':
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from mail_support import run_processor
    state = run_processor(os.environ['SYNTHETIC_MAIL_DIRECTORY'],
                          None if mode == 'success' else mode, message)
    assert not any(path == '/tmp/mail.log' or access != 'r' for path, access in state.opens)
    if state.error is not None:
        raise state.error
    if state.exit is not None:
        sys.exit(state.exit)
    assert state.completed and len(state.emails) == 1 and len(state.attachments) == 3
    assert len(state.tasks) == 1
print('SYNTHETIC_PRIVATE_MAIL_STDOUT')
print('PRIVACY_REQUEST status=200 msecs=0')
print('SYNTHETIC_PRIVATE_MAIL_STDERR', file=sys.stderr)
sys.exit(int(os.environ.get('SYNTHETIC_MAIL_EXIT', '0')))
