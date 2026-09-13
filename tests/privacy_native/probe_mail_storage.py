"""Independent release-gate probe, intentionally nonzero while legacy storage fails.

Run directly; this is not a green synthetic mail acceptance test. The actual
SavedFile method runs against in-memory text/binary handles, without importing
the application or touching storage. Its default must accept the MIME payload
type passed by process_email.save_attachment before deployment is accepted.
"""
import ast
import io
import os
from pathlib import Path
import types

ROOT = Path(__file__).resolve().parents[2]
source = ROOT / 'docassemble_webapp/docassemble/webapp/files/savedfile.py'
tree = ast.parse(source.read_text(), filename=str(source))
saved_file = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'SavedFile')
method = next(node for node in saved_file.body if isinstance(node, ast.FunctionDef) and node.name == 'write_content')
namespace = {'os': os, 'directory_for': lambda *_: '/synthetic',
             'open': lambda *args, **kwargs: io.BytesIO() if args[1] == 'wb' else io.StringIO()}
exec(compile(ast.Module(body=[method], type_ignores=[]), str(source), 'exec'), namespace)
instance = types.SimpleNamespace(filename='attachment', fix=lambda: None, save=lambda: None)
namespace['write_content'](instance, '{"synthetic": true}')
print('Text header control passed; probing decoded MIME bytes.', flush=True)
namespace['write_content'](instance, b'SYNTHETIC_PRIVATE_BODY')
print('Decoded MIME byte storage contract passed.', flush=True)
