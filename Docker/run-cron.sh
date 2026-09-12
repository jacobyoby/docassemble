#!/bin/bash
# Cron keeps its existing output pipe; only fixed diagnostics/counters reach it.
exec 3>&1
exec >/dev/null 2>&1

export DA_ROOT="${DA_ROOT:-/usr/share/docassemble}"
export DA_DEFAULT_LOCAL="local3.14"

startup_failure() {
    [ -x "${DA_ROOT}/webapp/privacy-diagnostic" ] || exit 69
    "${DA_ROOT}/webapp/privacy-diagnostic" cron "$1" >&3 3>&-
    exit $?
}
[ -x "${DA_ROOT}/webapp/privacy-diagnostic" ] || exit 69

# Drop privileges before Go establishes its child/process-death boundary.
shopt -s execfail
if [ "$EUID" -eq 0 ]; then
    DA_CRON_CHILD=''
    DA_CRON_SIGNAL=''
    forward_signal() {
        DA_CRON_SIGNAL=$1
        DA_CRON_INTERRUPTED=1
        [ -z "$DA_CRON_CHILD" ] || kill -s "$1" "$DA_CRON_CHILD"
    }
    trap 'forward_signal TERM' TERM
    trap 'forward_signal INT' INT
    /usr/bin/setpriv --reuid=www-data --regid=www-data --init-groups \
        /bin/bash "${BASH_SOURCE[0]}" "${1:-cron_daily}" >&3 3>&- &
    DA_CRON_CHILD=$!
    [ -z "$DA_CRON_SIGNAL" ] || kill -s "$DA_CRON_SIGNAL" "$DA_CRON_CHILD"
    while :; do
        DA_CRON_INTERRUPTED=0
        wait "$DA_CRON_CHILD"
        DA_CRON_STATUS=$?
        [ "$DA_CRON_INTERRUPTED" -eq 0 ] && break
    done
    trap '' TERM INT
    if [ "$DA_CRON_STATUS" -ne 0 ]; then
        "${DA_ROOT}/webapp/privacy-diagnostic" cron execution >&3 3>&-
    fi
    exit "$DA_CRON_STATUS"
fi
[ "$EUID" -eq "$(/usr/bin/id -u www-data)" ] || startup_failure launch
export USER=www-data LOGNAME=www-data SHELL=/bin/bash HOME=/var/www
DA_RUNTIME="${DA_PYTHON:-${DA_ROOT}/${DA_DEFAULT_LOCAL}}"
export DA_ACTIVATE="${DA_RUNTIME}/bin/activate"
source "${DA_ACTIVATE}" || startup_failure activation

export CRONTYPE=${1:-cron_daily}

export DA_CONFIG_FILE="${DA_CONFIG:-${DA_ROOT}/config/config.yml}"
DA_EXPORTS=$("${DA_RUNTIME}/bin/python" -m docassemble.base.read_config "$DA_CONFIG_FILE") || startup_failure config
source /dev/stdin <<< "$DA_EXPORTS" || startup_failure config_eval
unset DA_EXPORTS

set -- $LOCALE
export LANG=$1

export IN_CRON=true

[ -x "${DA_ROOT}/webapp/privacy-process" ] || startup_failure launch
exec /usr/bin/nice -n 19 "${DA_ROOT}/webapp/privacy-process" --component cron -- \
    "${DA_RUNTIME}/bin/flask" --app docassemble.webapp.server cron run "$CRONTYPE" >&3 3>&-
exec 3>&1 >/dev/null
startup_failure launch
