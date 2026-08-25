FROM python:3.12-slim

# The listener itself is stdlib-only. psycopg2 is needed only for the
# TimescaleDB sink (--database-url), which is how this image is normally run.
COPY requirements-db.txt /tmp/
RUN pip install --no-cache-dir -r /tmp/requirements-db.txt \
    && rm /tmp/requirements-db.txt

RUN useradd --system --no-create-home --shell /usr/sbin/nologin teltonika \
    && mkdir -p /var/log/teltonika \
    && chown teltonika:teltonika /var/log/teltonika

WORKDIR /opt/teltonika
COPY teltonika_listener.py db_sink.py io_definitions.json ./

# Configuration comes from the environment, not from baked-in flags. A CLI
# argument always beats an env default, so hardcoding flags in CMD would make
# every TELTONIKA_* variable silently inert. On Railway, point
# TELTONIKA_LOG_DIR at the mounted volume (/data/logs).
ENV TELTONIKA_HOST=0.0.0.0 \
    TELTONIKA_PORT=5027 \
    TELTONIKA_IO_DEFS=/opt/teltonika/io_definitions.json \
    TELTONIKA_LOG_DIR=/var/log/teltonika \
    TELTONIKA_LOG_LEVEL=INFO \
    TELTONIKA_IDLE_TIMEOUT=600 \
    TELTONIKA_MAX_CONNECTIONS=500

USER teltonika
EXPOSE 5027

# No ENTRYPOINT: a platform-supplied start command replaces CMD, and with an
# ENTRYPOINT present it would be appended to it instead, producing a garbled
# argv.
CMD ["python3", "-u", "/opt/teltonika/teltonika_listener.py"]
