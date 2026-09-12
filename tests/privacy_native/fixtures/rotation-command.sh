#!/bin/sh
# Synthetic stream only; executable stays in the read-only source mount.
trap 'exit 0' TERM INT QUIT
burst=0
while :; do
    if [ "$burst" -eq 0 ] && [ -e "$1" ]; then
        while [ "$burst" -lt 8192 ]; do
            printf '%s\n' 'SYNTHETIC_PRIVATE after rotation'
            burst=$((burst + 1))
        done
    fi
    printf '%s\n' 'SYNTHETIC_PRIVATE stdout query=synthetic.yml' 'PRIVACY_REQUEST status=200 msecs=1'
    printf '%s\n' 'SYNTHETIC_PRIVATE stderr 203.0.113.7' >&2
    sleep 0.05
done
