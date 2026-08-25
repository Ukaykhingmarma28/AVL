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

USER teltonika
EXPOSE 5027

ENTRYPOINT ["python3", "-u", "/opt/teltonika/teltonika_listener.py"]
CMD ["--host", "0.0.0.0", \
     "--port", "5027", \
     "--io-definitions", "/opt/teltonika/io_definitions.json", \
     "--log-dir", "/var/log/teltonika", \
     "--log-level", "INFO", \
     "--idle-timeout", "600", \
     "--max-connections", "500"]
