FROM python:3.14-alpine
# Development only: gcc supports Go race tests, bash runs the real launchers,
# and Supervisor/nginx exercise their real protocols with synthetic fixtures.
RUN apk add --no-cache build-base bash supervisor nginx
RUN adduser -S -D -H -u 82 -G www-data www-data
