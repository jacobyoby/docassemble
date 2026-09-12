#!/bin/bash
# Keep bootstrap output out of retained logs; report checked failures safely.
exec 3>&1
exec >/dev/null 2>&1

umask 002

export DA_ROOT="${DA_ROOT:-/usr/share/docassemble}"

export DA_DEFAULT_LOCAL="local3.14"

startup_failure() {
    [ -x "${DA_ROOT}/webapp/privacy-diagnostic" ] || exit 69
    "${DA_ROOT}/webapp/privacy-diagnostic" celery "$1" >&3 3>&-
    exit $?
}
[ -x "${DA_ROOT}/webapp/privacy-diagnostic" ] || exit 69
DA_RUNTIME="${DA_PYTHON:-${DA_ROOT}/${DA_DEFAULT_LOCAL}}"
export DA_ACTIVATE="${DA_RUNTIME}/bin/activate"
source "${DA_ACTIVATE}" || startup_failure activation

export DA_CONFIG_FILE="${DA_CONFIG:-${DA_ROOT}/config/config.yml}"
DA_EXPORTS=$("${DA_RUNTIME}/bin/python" -m docassemble.base.read_config --limited "$DA_CONFIG_FILE") || startup_failure config
source /dev/stdin <<< "$DA_EXPORTS" || startup_failure config_eval
unset DA_EXPORTS

set -- $LOCALE
export LANG=$1

export HOME=/var/www

valid_workers() {
    [[ "$1" =~ ^[1-9][0-9]{0,6}$ ]] && (( $1 <= 1048576 ))
}
NUMPROCS=$(nproc --all) || startup_failure config_eval
valid_workers "$NUMPROCS" && valid_workers "${DAMAXCELERYWORKERS:-}" || startup_failure config_eval
if [ -n "${DACELERYWORKERS:-}" ]; then
    valid_workers "$DACELERYWORKERS" || startup_failure config_eval
fi
if ((NUMPROCS > DAMAXCELERYWORKERS));
then
    NUMPROCS=${DAMAXCELERYWORKERS}
fi
NUMPROCS=${DACELERYWORKERS:-${NUMPROCS}}
NUMPROCS=$((NUMPROCS - 1))
if ((NUMPROCS < 1));
then
    NUMPROCS=1
fi

shopt -s execfail
exec "${DA_ROOT}/webapp/privacy-process" --component celery -- \
    "${DA_RUNTIME}/bin/celery" -A docassemble.webapp.worker worker --loglevel=INFO \
    --concurrency="$NUMPROCS" -Q celery >&3 3>&-
exec 3>&1 >/dev/null
startup_failure launch
