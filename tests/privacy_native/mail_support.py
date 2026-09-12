"""Run the real mail processor with synthetic database, storage, and task sinks."""
import builtins
import contextlib
import io
from pathlib import Path
import runpy
import sys
import types
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
MESSAGE = (b'From: Synthetic Sender <sender@example.invalid>\n'
           b'To: testcode@example.invalid\nEnvelope-to: testcode@example.invalid\n'
           b'Subject: SYNTHETIC_PRIVATE_SUBJECT\nMIME-Version: 1.0\n'
           b'Content-Type: multipart/mixed; boundary="synthetic-boundary"\n\n'
           b'--synthetic-boundary\nContent-Type: text/plain\n\nSYNTHETIC_PRIVATE_BODY\n'
           b'--synthetic-boundary\nContent-Type: application/pdf\n'
           b'Content-Disposition: attachment; filename="synthetic.pdf"\n'
           b'Content-Transfer-Encoding: base64\n\nAP9QREY=\n'
           b'--synthetic-boundary--\n')


def run_processor(directory, failure=None, message=MESSAGE):
    state = types.SimpleNamespace(opens=[], emails=[], attachments=[], saved=[], tasks=[], config=[],
                                  completed=False, exit=None, error=None)
    modules = {}

    def module(name, **attrs):
        value = types.ModuleType(name)
        value.__dict__.update(attrs)
        modules[name] = value
        parent, _, child = name.rpartition('.')
        if parent in modules:
            setattr(modules[parent], child, value)
        return value

    for name in ('docassemble', 'docassemble.base', 'docassemble.webapp',
                 'docassemble.webapp.emailserver', 'docassemble.webapp.files',
                 'docassemble.webapp.users', 'docassemble.webapp.tasks', 'sqlalchemy'):
        module(name, __path__=[])
    module('docassemble.base.config', load=lambda **kwargs: state.config.append(kwargs))

    class Query:
        def filter_by(self, **kwargs):
            return self

    class Session:
        def execute(self, query):
            if failure == 'database':
                raise OSError('SYNTHETIC_PRIVATE_DATABASE')
            row = None if failure == 'unknown' else types.SimpleNamespace(
                uid='synthetic-session', filename='synthetic.yml', user_id=None, temp_user_id=7)
            return types.SimpleNamespace(scalar=lambda: row)

        def add(self, record):
            pass

    @contextlib.contextmanager
    def session_scope():
        yield Session()

    def email_record(**kwargs):
        state.emails.append(kwargs)
        return types.SimpleNamespace(id=42, **kwargs)

    def attachment(**kwargs):
        state.attachments.append(kwargs)
        return types.SimpleNamespace(**kwargs)

    def saved_file(*args, **kwargs):
        return types.SimpleNamespace(write_content=state.saved.append, finalize=lambda: None)

    def signature(*args, **kwargs):
        state.tasks.append((args, kwargs))
        def delay():
            if failure == 'broker':
                raise OSError('SYNTHETIC_PRIVATE_BROKER')
        return types.SimpleNamespace(delay=delay)

    modules['sqlalchemy'].select = lambda *args: Query()
    module('sqlalchemy.orm', joinedload=lambda *args: None)
    module('docassemble.webapp.db', session_scope=session_scope)
    module('docassemble.webapp.emailserver.models', Shortener=object, Email=email_record,
           EmailAttachment=attachment)
    module('docassemble.webapp.files.file_number', get_new_file_number=lambda *args: 77)
    module('docassemble.webapp.files.savedfile', SavedFile=saved_file)
    module('docassemble.webapp.users.models', UserModel=object)
    module('docassemble.webapp.tasks.app', celery_app=types.SimpleNamespace(signature=signature))
    original_open = builtins.open
    message_path = str(Path(directory) / 'message')

    def opening(path, mode='r', *args, **kwargs):
        state.opens.append((str(path), mode))
        if str(path) == '/tmp/mail.log':
            # Never touch a real log even when executing the fail-first source.
            return io.StringIO()
        if str(path) == message_path:
            if failure == 'read':
                raise OSError('SYNTHETIC_PRIVATE_READ')
            return io.StringIO(message.decode('utf-8'))
        return original_open(path, mode, *args, **kwargs)

    with patch.dict(sys.modules, modules), patch.object(sys, 'argv', ['process_email.py', message_path]), \
            patch.object(builtins, 'open', opening):
        try:
            runpy.run_path(str(ROOT / 'docassemble_webapp/docassemble/webapp/process_email.py'), run_name='__main__')
            state.completed = True
        except SystemExit as exc:
            state.exit = exc.code
        except Exception as exc:
            state.error = exc
    return state
