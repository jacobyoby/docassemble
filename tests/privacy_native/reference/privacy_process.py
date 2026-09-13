"""Counters-only foreground process wrapper. POSIX, Python 3.14, no dependencies."""

from __future__ import annotations

import fcntl
import json
import math
import os
import resource
import selectors
import signal
import stat
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from typing import Protocol

CHUNK_BYTES = 4096
MAX_SNAPSHOT_BYTES = 8192
USAGE_FAILURE = 64
RUNNER_FAILURE = 70
SINK_FAILURE = 74
COUNTERS = (
    "status_1xx", "status_2xx", "status_3xx", "status_4xx", "status_5xx",
    "latency_fast", "latency_medium", "latency_slow", "latency_timeout",
    "unclassified", "rejected", "dropped",
)


class Aggregator(Protocol):
    def feed(self, stream: str, data: bytes) -> None: ...
    def finish(self, stream: str) -> None: ...
    def snapshot(self) -> dict[str, int | str]: ...


def _snapshot(aggregator: Aggregator, component: str) -> bytes:
    value = aggregator.snapshot()
    if type(value) is not dict or set(value) != {"schema", "component", *COUNTERS}:
        raise ValueError("invalid snapshot")
    if type(value["schema"]) is not int or value["schema"] != 1:
        raise ValueError("invalid snapshot")
    if type(value["component"]) is not str or value["component"] != component:
        raise ValueError("invalid snapshot")
    for key in COUNTERS:
        if type(value[key]) is not int or not 0 <= value[key] <= 2**31 - 1:
            raise ValueError("invalid snapshot")
    clean = {"schema": 1, "component": component}
    clean.update({key: value[key] for key in COUNTERS})
    encoded = json.dumps(clean, ensure_ascii=True, separators=(",", ":")).encode() + b"\n"
    if len(encoded) >= MAX_SNAPSHOT_BYTES:
        raise ValueError("invalid snapshot")
    return encoded


def _signal(pid: int, value: int, *, group: bool = False) -> None:
    try:
        (os.killpg if group else os.kill)(pid, value)
    except ProcessLookupError:
        pass


def _group_alive(pid: int) -> bool:
    try:
        os.killpg(pid, 0)
        return True
    except ProcessLookupError:
        return False


def _run(
    command: Sequence[str],
    component: str,
    sink_fd: int = 1,
    aggregator_class: Callable[[str], Aggregator] | None = None,
    *,
    require_parent_death: bool = True,
    snapshot_interval: float = 1.0,
    sink_timeout: float = 5.0,
    stop_grace: float = 2.0,
    kill_grace: float = 1.0,
) -> int:
    """Run one foreground master; return its exit code or a fixed wrapper failure.

    Call from the main thread of a dedicated process. This permanently disables
    core dumps for that process. Timing overrides exist for synthetic tests.
    Raw bytes are held only in a fixed read chunk and the injected aggregator.
    """
    if (
        type(component) is not str
        or component not in {"nginx", "uwsgi"}
        or isinstance(command, (str, bytes))
        or not isinstance(command, Sequence)
        or not command
        or any(type(arg) is not str or "\0" in arg for arg in command)
        or not os.path.isabs(command[0])
        or (component == "uwsgi" and "--die-on-term" not in command[1:])
        or type(sink_fd) is not int
        or sink_fd < 0
        or type(require_parent_death) is not bool
    ):
        return USAGE_FAILURE
    timings = (snapshot_interval, sink_timeout, stop_grace, kill_grace)
    if any(type(v) not in (int, float) or not math.isfinite(v) or v <= 0 for v in timings):
        return USAGE_FAILURE

    child: subprocess.Popen[bytes] | None = None
    sink: int | None = None
    sink_flags: int | None = None
    old_handlers: dict[int, object] = {}
    selector: selectors.BaseSelector | None = None
    signals = {"stop": 0, "forward": 0}
    failure = 0
    pipes: dict[int, str] = {}
    stop_started: float | None = None
    group_stopped = False
    killed_at: float | None = None
    pending: bytes | None = None
    pending_offset = 0
    pending_started = 0.0
    pending_version = 0
    version = 1
    written_version = 0
    next_snapshot = 0.0
    final = False
    aggregator_ok = True

    def handle(signum: int, _frame: object) -> None:
        if signum in (signal.SIGINT, signal.SIGTERM):
            signals["stop"] = signum
        elif signum == signal.SIGHUP:
            signals["forward"] |= 1
        elif signum == signal.SIGUSR1:
            signals["forward"] |= 2

    def stop(now: float) -> None:
        nonlocal stop_started
        if child is not None and stop_started is None:
            stop_started = now
            graceful = signal.SIGQUIT if component == "nginx" else signal.SIGTERM
            _signal(child.pid, graceful)
            # A master may already have exited while descendants retain pipes.
            if child.poll() is not None:
                _signal(child.pid, graceful, group=True)

    try:
        selector = selectors.DefaultSelector()
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        child_command = list(command)
        if require_parent_death:
            if sys.platform != "linux":
                return RUNNER_FAILURE
            helper = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pdeath_exec.py")
            if not stat.S_ISREG(os.stat(helper).st_mode):
                return RUNNER_FAILURE
            child_command = [sys.executable, "-I", "-B", helper, str(os.getpid()),
                             component, "--", *command]
        if aggregator_class is None:
            from log_aggregate import LogAggregator
            aggregator_class = LogAggregator
        aggregator = aggregator_class(component)
        _snapshot(aggregator, component)  # Validate before starting the service.
        try:
            sink = os.dup(sink_fd)
            mode = os.fstat(sink).st_mode
            if not (stat.S_ISFIFO(mode) or stat.S_ISSOCK(mode)):
                return SINK_FAILURE
            sink_flags = fcntl.fcntl(sink, fcntl.F_GETFL)
            fcntl.fcntl(sink, fcntl.F_SETFL, sink_flags | os.O_NONBLOCK)
        except OSError:
            return SINK_FAILURE
        for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP, signal.SIGUSR1):
            old_handlers[sig] = signal.signal(sig, handle)
        old_handlers[signal.SIGPIPE] = signal.signal(signal.SIGPIPE, signal.SIG_IGN)
        child = subprocess.Popen(
            child_command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, close_fds=True, start_new_session=True,
            bufsize=0,
        )
        for pipe, name in ((child.stdout, "stdout"), (child.stderr, "stderr")):
            assert pipe is not None
            os.set_blocking(pipe.fileno(), False)
            pipes[pipe.fileno()] = name
            selector.register(pipe, selectors.EVENT_READ)

        while True:
            now = time.monotonic()
            if signals["stop"] or failure:
                stop(now)
            forward = signals["forward"]
            signals["forward"] = 0
            if child.poll() is None and stop_started is None:
                if forward & 1:
                    _signal(child.pid, signal.SIGHUP)
                if forward & 2:
                    _signal(child.pid, signal.SIGUSR1)
            exit_code = child.poll()
            if exit_code is not None and (pipes or _group_alive(child.pid)):
                stop(now)

            if stop_started is not None and not group_stopped and (
                exit_code is not None or now - stop_started >= stop_grace / 2
            ):
                graceful = signal.SIGQUIT if component == "nginx" else signal.SIGTERM
                _signal(child.pid, graceful, group=True)
                group_stopped = True
            if stop_started is not None and now - stop_started >= stop_grace and killed_at is None:
                _signal(child.pid, signal.SIGKILL, group=True)
                killed_at = now
            if killed_at is not None and now - killed_at >= kill_grace:
                # Escaped descendants or unreaped groups cannot extend our wait.
                if pipes or child.poll() is None or _group_alive(child.pid):
                    failure = failure or RUNNER_FAILURE
                for key in list(selector.get_map().values()):
                    if aggregator_ok:
                        try:
                            aggregator.finish(pipes[key.fd])
                            version = (version + 1) & ((1 << 63) - 1)
                        except Exception:
                            aggregator_ok = False
                    selector.unregister(key.fileobj)
                    key.fileobj.close()
                pipes.clear()
                final = True
            elif exit_code is not None and not pipes and not _group_alive(child.pid):
                final = True

            if not failure and aggregator_ok:
                try:
                    if (pending is None or pending_offset == 0) and (final or now >= next_snapshot):
                        if version != written_version and (pending is None or pending_version != version):
                            encoded = _snapshot(aggregator, component)
                            if pending is None:
                                pending_started = now
                            pending = encoded
                            pending_offset = 0
                            pending_version = version
                        next_snapshot = now + snapshot_interval
                except Exception:
                    failure = RUNNER_FAILURE
                    aggregator_ok = False
                    stop(now)

            if pending is not None and not failure:
                try:
                    assert sink is not None
                    count = os.write(sink, memoryview(pending)[pending_offset:])
                    if count <= 0:
                        raise OSError("sink failed")
                    pending_offset += count
                    if pending_offset == len(pending):
                        written_version = pending_version
                        pending = None
                        pending_offset = 0
                except (BlockingIOError, InterruptedError):
                    pass
                except OSError:
                    failure = SINK_FAILURE
                    stop(now)
                if pending is not None and now - pending_started >= sink_timeout:
                    failure = SINK_FAILURE
                    stop(now)

            if failure:
                pending = None
            if final and (failure or (pending is None and written_version == version)):
                code = child.poll()
                if code is None:
                    return RUNNER_FAILURE
                return failure or (code if code >= 0 else 128 - code)

            for key, _events in selector.select(timeout=0.02):
                fd = key.fd
                try:
                    data = os.read(fd, CHUNK_BYTES)
                except (BlockingIOError, InterruptedError):
                    continue
                except OSError:
                    failure = failure or RUNNER_FAILURE
                    data = b""
                stream = pipes[fd]
                if not data:
                    selector.unregister(key.fileobj)
                    key.fileobj.close()
                    del pipes[fd]
                if aggregator_ok:
                    try:
                        if data:
                            aggregator.feed(stream, data)
                        else:
                            aggregator.finish(stream)
                        version = (version + 1) & ((1 << 63) - 1)
                    except Exception:
                        aggregator_ok = False
                        failure = failure or RUNNER_FAILURE
    except BaseException:
        # Never print exception text, argv, paths, or a raw-output fallback.
        if child is not None:
            try:
                graceful = signal.SIGQUIT if component == "nginx" else signal.SIGTERM
                _signal(child.pid, graceful, group=True)
                deadline = time.monotonic() + stop_grace
                while time.monotonic() < deadline and _group_alive(child.pid):
                    child.poll()
                    time.sleep(0.02)
            except OSError:
                pass
        return RUNNER_FAILURE
    finally:
        cleanup_failed = False
        if child is not None:
            try:
                if child.poll() is None or _group_alive(child.pid):
                    _signal(child.pid, signal.SIGKILL, group=True)
                child.wait(timeout=kill_grace)
            except (OSError, subprocess.TimeoutExpired):
                pass
            for pipe in (child.stdout, child.stderr):
                if pipe is not None:
                    try:
                        pipe.close()
                    except BaseException:
                        cleanup_failed = True
        if selector is not None:
            try:
                selector.close()
            except BaseException:
                cleanup_failed = True
        for sig, handler in old_handlers.items():
            try:
                signal.signal(sig, handler)
            except BaseException:
                cleanup_failed = True
        if sink is not None:
            if sink_flags is not None:
                try:
                    fcntl.fcntl(sink, fcntl.F_SETFL, sink_flags)
                except OSError:
                    cleanup_failed = True
            try:
                os.close(sink)
            except OSError:
                cleanup_failed = True
        if cleanup_failed:
            raise RuntimeError("runner cleanup failed")


def run(
    command: Sequence[str], component: str, sink_fd: int = 1,
    aggregator_class: Callable[[str], Aggregator] | None = None, *,
    require_parent_death: bool = True,
    snapshot_interval: float = 1.0, sink_timeout: float = 5.0,
    stop_grace: float = 2.0, kill_grace: float = 1.0,
) -> int:
    """Run a foreground child, requiring Linux parent-death protection by default.

    Portable synthetic callers can explicitly opt out with require_parent_death=False.
    Nginx additionally requires the reviewed main-context shutdown companion.
    """
    try:
        return _run(command, component, sink_fd, aggregator_class,
                    require_parent_death=require_parent_death,
                    snapshot_interval=snapshot_interval, sink_timeout=sink_timeout,
                    stop_grace=stop_grace, kill_grace=kill_grace)
    except BaseException:
        return RUNNER_FAILURE


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = list(sys.argv[1:] if argv is None else argv)
        if len(args) < 4 or args[0] != "--component" or args[2] != "--":
            return USAGE_FAILURE
        return run(args[3:], args[1], require_parent_death=True)
    except BaseException:
        return RUNNER_FAILURE


if __name__ == "__main__":
    raise SystemExit(main())
