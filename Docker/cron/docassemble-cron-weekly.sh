#! /bin/bash

export DA_ROOT="${DA_ROOT:-/usr/share/docassemble}"
# Internal handoff only; normal invocations always enter native capture.
if [ "${1:-}" != "--privacy-captured" ]; then
    exec 3>&1
    exec >/dev/null 2>&1
    [ -x "${DA_ROOT}/webapp/privacy-diagnostic" ] || exit 69
    shopt -s execfail
    exec "${DA_ROOT}/webapp/privacy-process" --component maintenance -- \
        /bin/bash "${BASH_SOURCE[0]}" --privacy-captured "$@" >&3 3>&-
    exec 3>&1 >/dev/null
    "${DA_ROOT}/webapp/privacy-diagnostic" maintenance launch >&3 3>&-
    exit $?
fi
shift

export DA_DEFAULT_LOCAL="local3.14"

export DA_ACTIVATE="${DA_PYTHON:-${DA_ROOT}/${DA_DEFAULT_LOCAL}}/bin/activate"
source "${DA_ACTIVATE}"
export DA_CONFIG_FILE="${DA_CONFIG:-${DA_ROOT}/config/config.yml}"
export CONTAINERROLE=":${CONTAINERROLE:-all}:"
source /dev/stdin < <(su -c "source \"${DA_ACTIVATE}\" && python -m docassemble.base.read_config \"${DA_CONFIG_FILE}\"" www-data)

set -- $LOCALE
export LANG=$1

if [[ $CONTAINERROLE =~ .*:(all|cron):.* ]]; then
    "${DA_ROOT}/webapp/run-cron.sh" cron_weekly
fi
