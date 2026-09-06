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

export DA_CONFIG_FILE="${DA_CONFIG:-${DA_ROOT}/config/config.yml}"
export DA_DEFAULT_LOCAL="local3.14"

export DA_ACTIVATE="${DA_PYTHON:-${DA_ROOT}/${DA_DEFAULT_LOCAL}}/bin/activate"
source "${DA_ACTIVATE}"
source /dev/stdin < <(python -m docassemble.base.read_config "$DA_CONFIG_FILE" )

if [ "${DAREADONLYFILESYSTEM:-false}" == "true" ]; then
    exit 0
fi

if [ "${DASUPERVISORUSERNAME:-null}" != "null" ]; then
    SUPERVISORCMD="supervisorctl --serverurl http://localhost:9001 --username ${DASUPERVISORUSERNAME} --password ${DASUPERVISORPASSWORD}"
else
    SUPERVISORCMD="supervisorctl --serverurl http://localhost:9001"
fi

if [ -e /var/run/uwsgi/docassemble.sock ]; then
    if [ "${DAROOTOWNED:-false}" == "true" ]; then
	if [ "${DAALLOWUPDATES:-true}" == "true" ] \
	   || [ "${DAENABLEPLAYGROUND:-true}" == "true" ] \
	   || [ "${DAALLOWCONFIGURATIONEDITING:-true}" == "true" ]; then
	    ${SUPERVISORCMD} stop uwsgi > /dev/null || exit 1
	    ${SUPERVISORCMD} start uwsgi > /dev/null || exit 1
	fi
    else
	${SUPERVISORCMD} stop uwsgi > /dev/null || exit 1
	${SUPERVISORCMD} start uwsgi > /dev/null || exit 1
    fi
fi

if [[ $CONTAINERROLE =~ .*:(all|celery):.* ]]; then
    ${SUPERVISORCMD} stop celery > /dev/null || exit 1
    ${SUPERVISORCMD} stop celerysingle > /dev/null || exit 1
    ${SUPERVISORCMD} start celery > /dev/null || exit 1
    ${SUPERVISORCMD} start celerysingle > /dev/null || exit 1
fi

if [[ $CONTAINERROLE =~ .*:(all|web):.* ]] && [ "${ENABLEMONITOR:-true}" = "true" ]; then
    ${SUPERVISORCMD} stop websockets > /dev/null || exit 1
    sleep 1
    ${SUPERVISORCMD} start websockets > /dev/null || exit 1
fi

if ${SUPERVISORCMD} status syslogng | grep -q RUNNING ; then
    ${SUPERVISORCMD} restart syslogng > /dev/null || exit 1
fi
