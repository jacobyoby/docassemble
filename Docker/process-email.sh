#!/bin/bash
# The message stays on stdin; retain only fixed diagnostics and Go counters.
exec 3>&1
exec >/dev/null 2>&1

export DA_ROOT="${DA_ROOT:-/usr/share/docassemble}"
export DA_DEFAULT_LOCAL="local3.14"

startup_failure() {
    if [ -x "${DA_ROOT}/webapp/privacy-diagnostic" ]; then
        "${DA_ROOT}/webapp/privacy-diagnostic" mail "$1" >&3 3>&-
    fi
    # Exim must retry failed delivery, including absent/broken diagnostics.
    exit 75
}
[ -x "${DA_ROOT}/webapp/privacy-diagnostic" ] || exit 75
DA_RUNTIME="${DA_PYTHON:-${DA_ROOT}/${DA_DEFAULT_LOCAL}}"
export DA_ACTIVATE="${DA_RUNTIME}/bin/activate"
source "${DA_ACTIVATE}" || startup_failure activation

shopt -s execfail
exec "${DA_ROOT}/webapp/privacy-process" --component mail -- \
    "${DA_RUNTIME}/bin/python" -m docassemble.webapp.process_email /dev/stdin >&3 3>&-
exec 3>&1 >/dev/null
startup_failure launch
