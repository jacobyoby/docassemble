"""Linux foreground exec helper. No fallback or raw diagnostics on failure."""
from __future__ import annotations

import errno
import os
import signal
import stat
import sys
from collections.abc import Sequence

FAILURE = 70


def _arm_parent_death(value: int) -> bool:
    import ctypes
    libc = ctypes.CDLL(None, use_errno=True)
    libc.prctl.argtypes = [ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong,
                          ctypes.c_ulong, ctypes.c_ulong]
    libc.prctl.restype = ctypes.c_int
    return libc.prctl(1, value, 0, 0, 0) == 0


def _ordinary_executable(path: str) -> bool:
    mode = os.stat(path).st_mode
    if not stat.S_ISREG(mode) or mode & (stat.S_ISUID | stat.S_ISGID):
        return False
    try:
        return not os.getxattr(path, "security.capability")
    except OSError as error:
        if error.errno in {errno.ENODATA, errno.ENOTSUP}:
            return True
        raise


def exec_guarded(parent: int, component: str, command: Sequence[str]) -> int:
    """Arm a native graceful signal, close the parent race, then replace this PID.

    Later credential changes inside the service can clear the kernel setting;
    launch profiles must prohibit those unless separately verified.
    """
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        if (
            sys.platform != "linux" or type(parent) is not int or not 1 < parent < 2**31
            or type(component) is not str or component not in {"nginx", "uwsgi"}
            or isinstance(command, (str, bytes)) or not isinstance(command, Sequence)
            or not command or any(type(arg) is not str or "\0" in arg for arg in command)
            or not os.path.isabs(command[0])
            or (component == "uwsgi" and "--die-on-term" not in command[1:])
            or not _ordinary_executable(command[0])
        ):
            return FAILURE
        graceful = signal.SIGQUIT if component == "nginx" else signal.SIGTERM
        if not _arm_parent_death(graceful) or os.getppid() != parent:
            return FAILURE
        os.execv(command[0], list(command))
    except BaseException:
        return FAILURE
    return FAILURE  # A successful exec never returns.


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = list(sys.argv[1:] if argv is None else argv)
        if len(args) < 4 or args[2] != "--":
            return FAILURE
        return exec_guarded(int(args[0]), args[1], args[3:])
    except BaseException:
        return FAILURE


if __name__ == "__main__":
    os._exit(main())
