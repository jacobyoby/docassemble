import os
import posixpath
import re
import stat

def splitall(path):
    allparts = []
    while 1:
        parts = os.path.split(path)
        if parts[0] == path:
            allparts.insert(0, parts[0])
            break
        if parts[1] == path:
            allparts.insert(0, parts[1])
            break
        path = parts[0]
        allparts.insert(0, parts[1])
    return allparts


def zip_member_is_safe(zinfo):
    """Reject ZIP members that could escape the target directory.

    Mirrors the tar ``filter='data'`` protection (PEP 706): absolute
    paths, ``..`` segments, and symlinks are refused before any member
    is read or written.
    """
    name = zinfo.filename
    if not name or posixpath.isabs(name) or re.match(r'^[A-Za-z]:[\\/]', name):
        return False
    if '..' in name.replace('\\', '/').split('/'):
        return False
    if stat.S_IFMT(zinfo.external_attr >> 16) == stat.S_IFLNK:
        return False
    return True
