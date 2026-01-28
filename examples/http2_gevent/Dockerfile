# HTTP/2 with Gevent Example
#
# Build: docker build -t gunicorn-http2-gevent .
# Run:   docker run -p 8443:8443 -v $(pwd)/certs:/certs:ro gunicorn-http2-gevent

FROM python:3.12-slim

# Install build dependencies for gevent and h2
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libc-dev \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy gunicorn source and install with gevent and http2 support
# For production, use: pip install gunicorn[gevent,http2]
COPY --chown=root:root . /gunicorn-src/
RUN pip install --no-cache-dir /gunicorn-src/[gevent,http2]

# Copy application files
COPY examples/http2_gevent/app.py /app/
COPY examples/http2_gevent/gunicorn_conf.py /app/

# Create non-root user for security
RUN useradd -m -u 1000 gunicorn && \
    chown -R gunicorn:gunicorn /app
USER gunicorn

EXPOSE 8443

# Health check
HEALTHCHECK --interval=10s --timeout=5s --start-period=5s --retries=3 \
    CMD python -c "import ssl,socket; s=socket.socket(); s.settimeout(2); ctx=ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE; ss=ctx.wrap_socket(s,server_hostname='localhost'); ss.connect(('localhost',8443)); ss.close()" || exit 1

# Run gunicorn with the config file
CMD ["gunicorn", "--config", "gunicorn_conf.py", "app:app"]
