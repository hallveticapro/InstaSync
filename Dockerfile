FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY scripts ./scripts
RUN python scripts/patch_instaloader_login.py

COPY app ./app

RUN if ! getent group 100 >/dev/null; then groupadd --gid 100 instasync; fi \
    && useradd --uid 99 --gid 100 --create-home --home-dir /home/instasync \
        --shell /usr/sbin/nologin instasync \
    && mkdir -p /data/cache \
    && chown -R 99:100 /app /data /home/instasync

USER instasync

EXPOSE 9000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:9000/healthz', timeout=3)"]

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "9000"]
