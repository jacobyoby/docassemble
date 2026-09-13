#!/usr/bin/env python3
"""Silent, bounded preflight for the maintained native privacy profile."""

import fnmatch
import os
import posixpath
import re
import selectors
import signal
import stat
import subprocess
import sys
import time


MAX_BYTES = 1024 * 1024
TIMEOUT_SECONDS = 10
INVALID = 70
UWSGI_FORMAT = "PRIVACY_REQUEST status=%(status) msecs=%(msecs)"
NGINX_FORMAT = "PRIVACY_REQUEST status=$status seconds=$request_time"
NGINX_COMMAND = ("/usr/sbin/nginx", "-T", "-e", "stderr")
_BOOL_OPTIONS = {"master", "enable-threads", "vhost", "manage-script-name", "die-on-term"}
_PATH_OPTIONS = {"socket", "venv", "pidfile", "touch-reload", "py-executable"}
_INT_OPTIONS = {"processes", "threads", "buffer-size", "max-fd"}
_OPTIONS = _BOOL_OPTIONS | _PATH_OPTIONS | _INT_OPTIONS | {
    "mount", "module", "callable", "http-socket", "log-format",
}
_LEVELS = {"debug", "info", "notice", "warn", "error", "crit", "alert", "emerg"}
_HEADER = re.compile(r"# configuration file (/[^\r\n]+):\r?\n?\Z")


class InvalidConfig(Exception):
    """Deliberately carries no input or exception detail."""


def _require(condition):
    if not condition:
        raise InvalidConfig()


def _text(data):
    _require(isinstance(data, bytes) and len(data) <= MAX_BYTES)
    text = data.decode("utf-8")
    _require(all(ord(char) >= 32 or char in "\n\r\t" for char in text))
    return text


def _absolute(value):
    return bool(re.fullmatch(r"/[A-Za-z0-9_./-]+", value)) and ".." not in value.split("/")


def validate_uwsgi(data):
    """Validate bytes; raise on rejection, return None on acceptance."""
    options = {}
    section = False
    text = _text(data)
    _require("{{" not in text and "}}" not in text)
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", ";")):
            continue
        if line.startswith("["):
            _require(not section and line == "[uwsgi]")
            section = True
            continue
        _require(section and "=" in line)
        key, value = (part.strip() for part in line.split("=", 1))
        _require(key in _OPTIONS and key not in options and bool(value))
        if key in _BOOL_OPTIONS:
            _require(value == "true")
        elif key in _PATH_OPTIONS:
            _require(_absolute(value))
        elif key in _INT_OPTIONS:
            _require(bool(re.fullmatch(r"[1-9][0-9]{0,6}", value)) and int(value) <= 1048576)
        elif key == "mount":
            prefix, separator, target = value.partition("=")
            _require(separator and (prefix == "/" or _absolute(prefix)))
            _require(target == "docassemble.webapp.run:application")
        elif key == "module":
            _require(value == "docassemble.webapp.listlog")
        elif key == "callable":
            _require(value == "app")
        elif key == "http-socket":
            _require(value == ":80")
        elif key == "log-format":
            _require(value == UWSGI_FORMAT)
        options[key] = value
    _require(section and options.get("master") == "true")
    _require(options.get("die-on-term") == "true" and options.get("log-format") == UWSGI_FORMAT)


def _dump_files(text):
    """Split nginx -T headers only outside quoted strings and comments."""
    files = {}
    first = None
    current = None
    body = []
    quote = None
    active = False

    def finish():
        if current is not None:
            content = "".join(body)
            _require(current not in files or files[current] == content)
            files[current] = content

    for line in text.splitlines(keepends=True):
        header = _HEADER.fullmatch(line) if quote is None else None
        if header:
            finish()
            current = header.group(1)
            _require(posixpath.normpath(current) == current)
            if first is None:
                first = current
            body = []
            continue
        _require(current is not None or not line.strip())
        body.append(line)
        for char in line:
            if quote:
                _require(char != "\\")
                if char == quote:
                    quote = None
            elif char == "#" and not active:
                break
            elif char in "\"'":
                quote = char
                active = True
            elif char == "\\":
                raise InvalidConfig()
            elif char.isspace() or char in ";{}":
                active = False
            else:
                active = True
        if quote is None:
            active = False
    _require(quote is None and first is not None)
    finish()
    return first, files


def _tokens(text):
    """Tokenize native delimiters, respecting quotes/comments and ${variables}."""
    result = []
    token = []
    active = False
    quote = None
    after_quote = False
    index = 0
    while index < len(text):
        char = text[index]
        if after_quote:
            _require(char.isspace() or char in ";{})")
            if char == ")":
                result.append(("word", "".join(token)))
                token, active = [], False
            after_quote = False
        if quote:
            _require(char != "\\")
            if char == quote:
                quote = None
                after_quote = True
            else:
                token.append(char)
        elif char == "#" and not active:
            index = text.find("\n", index)
            if index < 0:
                break
        elif char in "\"'":
            _require(not active)
            quote, active = char, True
        elif char == "\\":
            raise InvalidConfig()
        elif char == "$" and text[index:index + 2] == "${":
            end = text.find("}", index + 2)
            _require(end >= 0 and bool(re.fullmatch(r"[A-Za-z0-9_]+", text[index + 2:end])))
            token.append(text[index:end + 1])
            active, index = True, end
        elif char.isspace() or char in ";{}":
            if active:
                result.append(("word", "".join(token)))
                token, active = [], False
            if char in ";{}":
                result.append((char, char))
        else:
            token.append(char)
            active = True
        index += 1
    _require(quote is None)
    if active:
        result.append(("word", "".join(token)))
    _require(len(result) <= 100000)
    return result


def _parse(text):
    root = []
    stack = [root]
    words = []
    for kind, value in _tokens(text):
        if kind == "word":
            words.append(value)
        elif kind in (";", "{"):
            _require(bool(words) and bool(words[0]))
            children = [] if kind == "{" else None
            stack[-1].append((tuple(words), children))
            words = []
            if children is not None:
                stack.append(children)
                _require(len(stack) <= 64)
        else:
            _require(not words and len(stack) > 1)
            stack.pop()
    _require(not words and len(stack) == 1)
    return root


def validate_nginx_dump(data):
    """Validate the complete successful -T stdout, including include contexts."""
    first, files = _dump_files(_text(data))
    trees = {name: _parse(body) for name, body in files.items()}
    seen = set()
    budget = 100000
    main = {}
    http_scopes = []

    def walk(nodes, context, scope, chain):
        nonlocal budget
        for words, children in nodes:
            budget -= 1
            _require(budget >= 0)
            name, args = words[0], words[1:]
            if name == "include":
                _require(children is None and len(args) == 1 and "$" not in args[0])
                pattern = args[0]
                if not pattern.startswith("/"):
                    pattern = posixpath.join(posixpath.dirname(first), pattern)
                pattern = posixpath.normpath(pattern)
                parts = pattern.split("/")
                matches = sorted(path for path in trees
                                 if len(path.split("/")) == len(parts)
                                 and all(fnmatch.fnmatchcase(part, glob)
                                         for part, glob in zip(path.split("/"), parts)))
                _require(matches or any(char in pattern for char in "*?["))
                for path in matches:
                    _require(path not in chain)
                    seen.add(path)
                    walk(trees[path], context, scope, chain + (path,))
                continue
            if name in {"access_log", "error_log", "worker_shutdown_timeout", "master_process", "daemon"}:
                _require(children is None and name not in scope)
                scope[name] = args
                if name == "access_log":
                    _require(args in (("off",), ("/dev/stdout", "privacy_counts")))
                    _require(bool(context) and context[0] == "http")
                elif name == "error_log":
                    _require(args == ("stderr",) or (len(args) == 2 and args[0] == "stderr" and args[1] in _LEVELS))
                elif name == "worker_shutdown_timeout":
                    _require(not context and args == ("2s",))
                elif name == "master_process":
                    _require(not context and args == ("on",))
                elif name == "daemon":
                    _require(not context and args == ("off",))
            elif name == "log_format":
                _require(children is None and len(args) >= 2 and context == ("http",))
                key = ("log_format", args[0])
                _require(key not in scope)
                scope[key] = args[1:]
                if args[0] == "privacy_counts":
                    _require(args == ("privacy_counts", NGINX_FORMAT))
            if children is not None:
                child_scope = {}
                if name == "http":
                    _require(not context and not args)
                    http_scopes.append(child_scope)
                walk(children, context + (name,), child_scope, chain)

    seen.add(first)
    walk(trees[first], (), main, (first,))
    _require(seen == set(trees))
    _require("error_log" in main and main.get("worker_shutdown_timeout") == ("2s",))
    _require(len(http_scopes) == 1)
    _require(http_scopes[0].get("access_log") == ("/dev/stdout", "privacy_counts"))
    _require(http_scopes[0].get(("log_format", "privacy_counts")) == (NGINX_FORMAT,))


def _nginx_dump():
    process = subprocess.Popen(NGINX_COMMAND, stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               start_new_session=True, close_fds=True)
    total = 0
    output = bytearray()
    deadline = time.monotonic() + TIMEOUT_SECONDS
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ, True)
            selector.register(process.stderr, selectors.EVENT_READ, False)
            while selector.get_map():
                remaining = deadline - time.monotonic()
                _require(remaining > 0)
                for key, _ in selector.select(min(remaining, 0.1)):
                    chunk = os.read(key.fd, 8192)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    total += len(chunk)
                    _require(total <= MAX_BYTES)
                    if key.data:
                        output.extend(chunk)
            remaining = deadline - time.monotonic()
            _require(remaining > 0 and process.wait(timeout=remaining) == 0)
        return bytes(output)
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=1)
        process.stdout.close()
        process.stderr.close()


def main(argv=None):
    try:
        args = sys.argv[1:] if argv is None else argv
        if len(args) == 2 and args[0] == "uwsgi":
            descriptor = os.open(args[1], os.O_RDONLY | os.O_NONBLOCK)
            with os.fdopen(descriptor, "rb") as source:
                _require(stat.S_ISREG(os.fstat(source.fileno()).st_mode))
                validate_uwsgi(source.read(MAX_BYTES + 1))
        elif args == ["nginx"]:
            validate_nginx_dump(_nginx_dump())
        else:
            return INVALID
        return 0
    except BaseException:
        return INVALID


if __name__ == "__main__":
    sys.exit(main())
