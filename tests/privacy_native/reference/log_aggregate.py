import re

_MAX_LINE = 4096
_COUNTER_MAX = 2**31 - 1
_SCHEMA_VERSION = 1

VALID_COMPONENTS = frozenset({"nginx", "uwsgi"})
VALID_STREAMS = frozenset({"stdout", "stderr"})

_STATUS_FAMILIES = {
    "1xx": (100, 199),
    "2xx": (200, 299),
    "3xx": (300, 399),
    "4xx": (400, 499),
    "5xx": (500, 599),
}

_STATUS_RE = re.compile(r"^[1-5][0-9]{2}$")
_MSECS_RE = re.compile(r"^(?:0|[1-9][0-9]*)$")
_SECONDS_RE = re.compile(r"(0|[1-9][0-9]{0,2})\.([0-9]{3})")


class LogAggregator:

    def __init__(self, component):
        if type(component) is not str or component not in VALID_COMPONENTS:
            raise ValueError(
                "component must be exactly 'nginx' or 'uwsgi'"
            )
        self._component = component
        self._buf = {"stdout": b"", "stderr": b""}
        self._dropping = {"stdout": False, "stderr": False}
        self._counters = {
            "schema": _SCHEMA_VERSION,
            "component": component,
            "status_1xx": 0,
            "status_2xx": 0,
            "status_3xx": 0,
            "status_4xx": 0,
            "status_5xx": 0,
            "latency_fast": 0,
            "latency_medium": 0,
            "latency_slow": 0,
            "latency_timeout": 0,
            "unclassified": 0,
            "rejected": 0,
            "dropped": 0,
        }

    def _inc(self, key):
        if self._counters[key] < _COUNTER_MAX:
            self._counters[key] += 1

    def _validate_stream(self, stream):
        if type(stream) is not str:
            raise TypeError("stream must be str")
        if stream not in VALID_STREAMS:
            raise ValueError("stream must be 'stdout' or 'stderr'")

    def feed(self, stream, chunk):
        self._validate_stream(stream)
        if type(chunk) is not bytes:
            raise TypeError("chunk must be bytes")

        buf = self._buf[stream]
        chunk_len = len(chunk)
        cpos = 0

        while cpos < chunk_len:
            if self._dropping[stream]:
                nl = chunk.find(b"\n", cpos)
                if nl == -1:
                    return
                self._dropping[stream] = False
                cpos = nl + 1
                continue

            nl = chunk.find(b"\n", cpos)
            if nl == -1:
                remaining = chunk_len - cpos
                if len(buf) + remaining > _MAX_LINE:
                    self._dropping[stream] = True
                    self._inc("dropped")
                    self._buf[stream] = b""
                    return
                self._buf[stream] = buf + chunk[cpos:]
                return

            line_len = len(buf) + (nl - cpos)
            if line_len > _MAX_LINE:
                self._inc("dropped")
                cpos = nl + 1
                buf = b""
                continue

            line = buf + chunk[cpos:nl]
            cpos = nl + 1
            buf = b""
            self._process_line(line)

        self._buf[stream] = buf

    def _process_line(self, line):
        if line.endswith(b"\r"):
            line = line[:-1]

        try:
            text = line.decode("utf-8")
        except UnicodeDecodeError:
            self._inc("rejected")
            return

        if b"\x00" in line or b"\r" in line:
            self._inc("rejected")
            return

        parts = text.split(" ")
        if not parts or parts[0] != "PRIVACY_REQUEST":
            self._inc("unclassified")
            return

        if len(parts) != 3:
            self._inc("rejected")
            return

        if not parts[1].startswith("status="):
            self._inc("rejected")
            return
        status_str = parts[1][7:]
        if not _STATUS_RE.fullmatch(status_str):
            self._inc("rejected")
            return
        status = int(status_str)

        if parts[2].startswith("msecs="):
            msecs_str = parts[2][6:]
            if len(msecs_str) > 6 or not _MSECS_RE.fullmatch(msecs_str):
                self._inc("rejected")
                return
            msecs = int(msecs_str)
        elif self._component == "nginx" and parts[2].startswith("seconds="):
            match = _SECONDS_RE.fullmatch(parts[2][8:])
            if match is None:
                self._inc("rejected")
                return
            msecs = int(match[1]) * 1000 + int(match[2])
        else:
            self._inc("rejected")
            return

        if not (0 <= msecs <= 600000):
            self._inc("rejected")
            return

        for fam, (lo, hi) in _STATUS_FAMILIES.items():
            if lo <= status <= hi:
                self._inc("status_" + fam)
                break

        if msecs < 100:
            self._inc("latency_fast")
        elif msecs < 1000:
            self._inc("latency_medium")
        elif msecs < 30000:
            self._inc("latency_slow")
        else:
            self._inc("latency_timeout")

    def snapshot(self):
        return dict(self._counters)

    def finish(self, stream):
        self._validate_stream(stream)
        was_dropping = self._dropping[stream]
        self._dropping[stream] = False
        buf = self._buf[stream]
        self._buf[stream] = b""
        if was_dropping:
            if buf:
                self._inc("dropped")
            return
        if buf:
            if len(buf) <= _MAX_LINE:
                self._process_line(buf)
            else:
                self._inc("dropped")
