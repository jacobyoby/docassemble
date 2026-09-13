ARG NATIVE_BASE=privacy-candidate-check
FROM ${NATIVE_BASE}
# Test-only compiler support comes from the existing protocol fixture image.
# Reuse the application's pinned build backend; no service image is changed.
COPY uwsgi-requirements.txt /tmp/uwsgi-requirements.txt
RUN apk add --no-cache linux-headers \
    && python3.14 -m pip install --no-cache-dir --no-deps setuptools==83.0.0 \
    && UWSGI_BUILD_CORES=2 python3.14 -m pip install --no-cache-dir --no-deps \
       --no-build-isolation --require-hashes -r /tmp/uwsgi-requirements.txt \
    && rm /tmp/uwsgi-requirements.txt \
    && python3.14 -m venv --without-pip /usr/share/docassemble/local3.14 \
    && ln -s /usr/local/bin/uwsgi /usr/share/docassemble/local3.14/bin/uwsgi
