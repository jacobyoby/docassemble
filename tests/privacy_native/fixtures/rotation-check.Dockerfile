ARG NATIVE_BASE=privacy-candidate-check
FROM ${NATIVE_BASE}
# Test-only native file rotation and forwarding acceptance; no service image changes.
RUN apk add --no-cache logrotate syslog-ng
