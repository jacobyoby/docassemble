#!/bin/bash
# Discard raw bootstrap output; report failures with bounded fixed records.
exec 3>&1
exec >/dev/null 2>&1

export DEBIAN_FRONTEND=noninteractive
export DA_ROOT="${DA_ROOT:-/usr/share/docassemble}"
export DA_CONFIG_FILE="${DA_CONFIG:-${DA_ROOT}/config/config.yml}"
export DA_DEFAULT_LOCAL="local3.14"
startup_failure() {
    [ -x "${DA_ROOT}/webapp/privacy-diagnostic" ] || exit 69
    "${DA_ROOT}/webapp/privacy-diagnostic" uwsgilog "$1" >&3 3>&-
    exit $?
}
[ -x "${DA_ROOT}/webapp/privacy-diagnostic" ] || exit 69
DA_RUNTIME="${DA_PYTHON:-${DA_ROOT}/${DA_DEFAULT_LOCAL}}"
export DA_ACTIVATE="${DA_RUNTIME}/bin/activate"
source "${DA_ACTIVATE}" || startup_failure activation
DA_EXPORTS=$("${DA_RUNTIME}/bin/python" -m docassemble.base.read_config --limited "$DA_CONFIG_FILE") || startup_failure config
source /dev/stdin <<< "$DA_EXPORTS" || startup_failure config_eval
unset DA_EXPORTS

set -- $LOCALE
export LANG=$1
export HOME=/var/www

# uWSGI environment options must not add a hidden logger, daemon, or UID change.
for DA_UWSGI_OPTION in ${!UWSGI_@}; do
    unset "$DA_UWSGI_OPTION"
done
unset DA_UWSGI_OPTION

DA_INI="${DA_ROOT}/config/docassemblelog.ini"

unset DAWEBSERVER
"${DA_ROOT}/webapp/privacy-preflight" uwsgi "$DA_INI" || startup_failure preflight
shopt -s execfail
exec "${DA_ROOT}/webapp/privacy-process" \
    --component uwsgi -- "${DA_RUNTIME}/bin/uwsgi" --ini "$DA_INI" \
    --die-on-term --log-format 'PRIVACY_REQUEST status=%(status) msecs=%(msecs)' >&3 3>&-
# Failed exec keeps its redirections: recover the saved sink from stdout.
exec 3>&1 >/dev/null
startup_failure launch
