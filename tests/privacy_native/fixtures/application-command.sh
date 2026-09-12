#!/bin/sh
# Synthetic service/configuration command for the disposable Supervisor test.
if [ "$1" = '-m' ]; then
    printf '%s\n' 'export LOCALE="C.UTF-8 UTF-8"' 'DAMAXCELERYWORKERS=4' 'DACELERYWORKERS=3'
    printf 'SYNTHETIC_PRIVATE_BOOTSTRAP\n' >&2
    exit 0
fi
# Run real base logging/application initialization through the production
# launcher and Go binary before the synthetic native-output controls.
application_logs=$(mktemp -d) || exit 98
python3.14 -B /review/tests/privacy_native/fixtures/application-logger.py \
    /review "$application_logs" web none info || exit 98
rmdir "$application_logs" || exit 98
printf '%s\n' 'SYNTHETIC_PRIVATE_NATIVE' 'PRIVACY_REQUEST status=200 msecs=0'
printf '%s\n' 'SYNTHETIC_PRIVATE_NATIVE' 'PRIVACY_REQUEST status=500 msecs=0' >&2
sleep 6
exit 74
