import logging
import json
import datetime


SAFE_EVENT_CODES = frozenset({
    "FORM_START",
    "FORM_SUBMIT",
    "FORM_ERROR",
    "SESSION_START",
    "SESSION_END",
    "AUTH_CHECK",
    "PDF_GENERATE",
})

EVENT_UNKNOWN = "UNKNOWN"

_LEVEL_MAP = {
    logging.DEBUG: "DEBUG",
    logging.INFO: "INFO",
    logging.WARNING: "WARNING",
    logging.ERROR: "ERROR",
    logging.CRITICAL: "CRITICAL",
}

SVC = "docassemble"
COMP = "app"

_TS_EPOCH = 0.0
_TS_UPPER = 4102444800.0

_MISSING = "___"

_FALLBACK = json.dumps({
    "ts": "1970-01-01T00:00:00Z",
    "level": "UNKNOWN",
    "svc": SVC,
    "comp": COMP,
    "event": EVENT_UNKNOWN,
}, sort_keys=True)


class PrivacyFormatter(logging.Formatter):
    """Strict-allowlist logging formatter.

    Output contains ONLY:
      - ts: validated finite numeric UTC timestamp from record.created
      - level: canonical string from exact type(levelno) is int mapping
      - svc: fixed service label
      - comp: fixed component label
      - event: membership-checked code from SAFE_EVENT_CODES

    ALL other LogRecord fields are ignored: name, msg, args, pathname,
    lineno, safe_diag, exc_info, stack_info, and any arbitrary attributes
    (clientip, yamlfile, session, user, etc).

    Untrusted objects are never stringified. Exact type() checks prevent
    hostile subclasses with custom __str__/__repr__/__eq__.

    On any error, returns a static JSON fallback string.
    """

    @classmethod
    def _safe_str(cls, x):
        if type(x) is str and x is not _MISSING:
            return x
        return _MISSING

    def format(self, record):
        try:
            if not isinstance(record, logging.LogRecord):
                return _FALLBACK

            lvl = record.levelno
            if type(lvl) is int and lvl in _LEVEL_MAP:
                level = _LEVEL_MAP[lvl]
            else:
                level = "UNKNOWN"

            event = self._safe_str(getattr(record, "event_code", None))
            if event not in SAFE_EVENT_CODES:
                event = EVENT_UNKNOWN

            ts_raw = record.created
            if type(ts_raw) not in (int, float):
                ts_out = "1970-01-01T00:00:00Z"
            elif ts_raw != ts_raw or ts_raw == float("inf") or ts_raw == float("-inf"):
                ts_out = "1970-01-01T00:00:00Z"
            elif not (_TS_EPOCH <= ts_raw <= _TS_UPPER):
                ts_out = "1970-01-01T00:00:00Z"
            else:
                ts_out = datetime.datetime.fromtimestamp(
                    float(ts_raw), tz=datetime.timezone.utc
                ).strftime("%Y-%m-%dT%H:%M:%SZ")

            out = {
                "ts": ts_out,
                "level": level,
                "svc": SVC,
                "comp": COMP,
                "event": event,
            }
            return json.dumps(out, sort_keys=True)
        except Exception:
            return _FALLBACK


class PrivacyStreamHandler(logging.StreamHandler):
    """Stream handler that never emits raw record data.

    Always uses PrivacyFormatter regardless of setFormatter() calls.
    Overrides emit() to bypass the standard formatter dispatch, so that
    default construction, setFormatter(None), or replacement with a
    generic logging.Formatter cannot cause raw record output.

    Overrides handleError to prevent the standard behavior of writing
    raw record.msg/args to stderr when a write or flush fails.
    Maintains a bounded local failure counter.

    Does not open files, call networking, or invoke subprocess.
    """

    _FAILURE_MAX = 99

    def __init__(self, stream=None):
        super().__init__(stream)
        self._failure_count = 0
        self._safe_fmt = PrivacyFormatter()

    def setFormatter(self, fmt=None):
        pass

    def emit(self, record):
        try:
            msg = self._safe_fmt.format(record)
            self.stream.write(msg + self.terminator)
            self.flush()
        except Exception:
            self.handleError(record)

    def flush(self):
        try:
            self.stream.flush()
        except Exception:
            if self._failure_count < self._FAILURE_MAX:
                self._failure_count += 1

    def handleError(self, record):
        if self._failure_count < self._FAILURE_MAX:
            self._failure_count += 1

    @property
    def failure_count(self):
        return self._failure_count


def safe_format_record(record):
    """Format a LogRecord into safe JSON. Returns _FALLBACK for non-records."""
    fmt = PrivacyFormatter()
    return fmt.format(record)
