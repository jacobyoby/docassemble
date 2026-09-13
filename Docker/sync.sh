#!/bin/bash

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
export DA_CONFIG_FILE="${DA_CONFIG:-${DA_ROOT}/config/config.yml}"
source /dev/stdin < <(su -c "source \"${DA_ACTIVATE}\" && python -m docassemble.base.read_config \"${DA_CONFIG_FILE}\"" www-data)

set -- $LOCALE
export LANG=$1

export CONTAINERROLE=":${CONTAINERROLE:-all}:"
export LOGDIRECTORY="${LOGDIRECTORY:-${DA_ROOT}/log}"

if [ "${DAWEBSERVER:-nginx}" = "apache" ]; then
    if [[ $CONTAINERROLE =~ .*:(all):.* ]]; then
	rsync -auq /var/log/apache2/ "${LOGDIRECTORY}/" && chown -R www-data:www-data "${LOGDIRECTORY}"
    fi
fi
if [ "${DAWEBSERVER:-nginx}" = "nginx" ]; then
    if [[ $CONTAINERROLE =~ .*:(all):.* ]]; then
	rsync -auq /var/log/nginx/ "${LOGDIRECTORY}/" && chown -R www-data:www-data "${LOGDIRECTORY}"
    fi
fi

if [[ $CONTAINERROLE =~ .*:(log):.* ]]; then
    rsync -auq --delete "${LOGDIRECTORY}/" /var/www/html/log/ && chown -R www-data:www-data /var/www/html/log
fi
