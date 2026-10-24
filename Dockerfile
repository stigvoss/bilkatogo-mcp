# Base image pinned by digest (python:3.12-slim). Update deliberately: docker pull, then copy the new digest.
FROM python:3.12-slim@sha256:a0f57064cbdcd6285fa45f51237ab0b35ea8ebaed06a1f5973e89e19dfb86704

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
# Hash-pinned dependencies exported from uv.lock (regenerate: see README).
COPY requirements.txt .
RUN pip install --no-cache-dir --require-hashes -r requirements.txt
COPY server.py .
RUN useradd --system --uid 10001 app && mkdir /data && chown app /data
VOLUME /data
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz',timeout=3).status==200 else 1)"
CMD ["python", "server.py"]
