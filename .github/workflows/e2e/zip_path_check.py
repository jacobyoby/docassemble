"""ZIP member validation check for docassemble#39 (H-7).

Run inside the docassemble container venv after installing this branch's
common.py, mirroring the other e2e *_check.py scripts:
    docker cp docassemble_webapp/docassemble/webapp/develop/common.py da:<site-packages>/docassemble/webapp/develop/common.py
    docker exec da <venv-python> /tmp/zip_path_check.py

Crafted member paths (absolute, dot-dot, symlinks) must be refused
while ordinary package members pass.
"""
import stat
import zipfile

from docassemble.webapp.utils.path import zip_member_is_safe


def make_info(name, is_symlink=False):
    info = zipfile.ZipInfo(filename=name)
    if is_symlink:
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
    return info


failures = []


def check(label, func):
    try:
        func()
    except Exception as err:
        failures.append(label)
        print("FAIL " + label + ": " + type(err).__name__ + " " + str(err)[:150])
    else:
        print("PASS " + label)


def legit_members_pass():
    for name in [
        'pkg/docassemble/base/data/questions/q.yml',
        'pkg/setup.py',
        'pkg/docassemble/',
        'README.md',
        'pkg/data/templates/form.pdf',
    ]:
        assert zip_member_is_safe(make_info(name)), name


def dotdot_rejected():
    for name in ['../../evil.py', 'pkg/../../evil.py', 'pkg/data/../../../evil.py', '..\\evil.py']:
        assert not zip_member_is_safe(make_info(name)), name


def absolute_rejected():
    for name in ['/etc/cron.d/evil', 'C:\\Windows\\evil.py', 'C:/evil.py']:
        assert not zip_member_is_safe(make_info(name)), name


def symlink_rejected():
    assert not zip_member_is_safe(make_info('pkg/link.py', is_symlink=True))


def empty_rejected():
    assert not zip_member_is_safe(make_info(''))


check("legit members pass", legit_members_pass)
check("dot-dot rejected", dotdot_rejected)
check("absolute rejected", absolute_rejected)
check("symlink rejected", symlink_rejected)
check("empty rejected", empty_rejected)

if failures:
    raise SystemExit("zip_path_check FAILED: " + ", ".join(failures))
print("zip_path_check: all checks passed")
