FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Europe/Prague \
    NVR_CONFIG=/etc/nvr/config.yaml \
    FORWARDED_ALLOW_IPS=*

RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg python3 python3-venv tzdata ca-certificates \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/nvr
COPY requirements.txt .
RUN python3 -m venv /opt/venv && /opt/venv/bin/pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY web ./web
RUN printf '#!/bin/sh\ncd /opt/nvr && exec /opt/venv/bin/python -m app.cli "$@"\n' > /usr/local/bin/nvr-cli \
 && chmod +x /usr/local/bin/nvr-cli \
 && mkdir -p /var/lib/nvr /recordings /go2rtc-config \
 && chown -R ubuntu:ubuntu /var/lib/nvr /go2rtc-config

# uid 1000 (user "ubuntu" in the base image)
USER ubuntu
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python3 -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/healthz')"
CMD ["/opt/venv/bin/uvicorn", "--factory", "app.main:create_app", "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--no-server-header"]
