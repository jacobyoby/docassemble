"""Fail-first check that PDF fills normalise text to NFC (accented names).

Usage (inside the docassemble container, with its venv python):
    nfc_check.py <fillable.pdf> <text_field_name> expect-fail|expect-pass

NFD input is routine from macOS/iOS dictation, option-key entry, and Apple
copy-paste, and browsers do not normalise it on submit. The stock XFDF fill
path loses the combining marks, so a name like "José" lands on the court
filing without its accent, with no error and nothing visible to the filer.
The fix normalises every string to NFC before the XFDF write.

expect-fail: the stock release must NOT produce the NFC form (proves the check
detects the defect). expect-pass: the filled field must be exactly NFC.
"""
import subprocess
import sys
import unicodedata

import docassemble.base.config

docassemble.base.config.load(arguments=['/usr/share/docassemble/config/config.yml'])

from docassemble.base.pdftk import fill_template  # noqa: E402  (after config load)

pdf, field, mode = sys.argv[1], sys.argv[2], sys.argv[3]
nfd = 'José'                      # e + combining acute, as dictation produces it
nfc = unicodedata.normalize('NFC', nfd)  # 'José' with U+00E9
assert nfd != nfc and len(nfd) == 5 and len(nfc) == 4

out = fill_template(pdf, data_strings=[(field, nfd)])
dump = subprocess.run(['pdftk', out, 'dump_data_fields_utf8'], capture_output=True, check=True).stdout.decode('utf-8', 'replace')

value = None
block = []
for line in dump.splitlines() + ['---']:
    if line.startswith('---'):
        if any(l == 'FieldName: ' + field for l in block):
            for l in block:
                if l.startswith('FieldValue: '):
                    value = l[len('FieldValue: '):]
        block = []
    else:
        block.append(line)

if value is None:
    print('could not read back field %r from the filled PDF; dump was:\n%s' % (field, dump[:800]))
    sys.exit(2)

is_nfc = (value == nfc)
print('field=%s value=%r nfc=%s codepoints=%s' % (field, value, is_nfc, [hex(ord(c)) for c in value]))

if mode == 'expect-fail':
    if is_nfc:
        print('CONTROL FAILED: the stock release already writes NFC; the check cannot prove the fix')
        sys.exit(1)
    print('control ok: stock fill does not produce the NFC form')
elif mode == 'expect-pass':
    if not is_nfc:
        print('FAIL: filled value is not the NFC form')
        sys.exit(1)
    print('pass: accented name round-trips as NFC')
else:
    print('mode must be expect-fail or expect-pass')
    sys.exit(2)
