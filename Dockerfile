FROM python:3.12-slim

# Stdlib only, so there is nothing to pip install.

RUN useradd --system --no-create-home --shell /usr/sbin/nologin teltonika \
    && mkdir -p /var/log/teltonika \
    && chown teltonika:teltonika /var/log/teltonika

WORKDIR /opt/teltonika
COPY teltonika_listener.py io_definitions.json ./

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
