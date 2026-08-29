FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PLAYWRIGHT_BROWSERS_PATH=/app/browser \
    AUTOSURF_REPOSITORY=https://github.com/fengzhanhuaer/AutoSurf.git \
    AUTOSURF_BRANCH=main

RUN apt-get update \
    && apt-get install --no-install-recommends -y \
        git tini novnc websockify x11vnc wmctrl x11-utils x11-xkb-utils x11-xserver-utils \
        libx11-xcb1 libxcb-dri3-0 libxkbcommon0 libxdamage1 libxfixes3 \
        libxtst6 libxext6 libpulse0 \
    && pip install --no-cache-dir playwright==1.61.0 \
    && python -m playwright install-deps chromium \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 autosurf

RUN set -eux; \
    architecture="$(dpkg --print-architecture)"; \
    case "$architecture" in amd64|arm64) ;; *) echo "Unsupported Chrome architecture: $architecture" >&2; exit 1 ;; esac; \
    python -c "import urllib.request; urllib.request.urlretrieve('https://dl.google.com/linux/direct/google-chrome-stable_current_${architecture}.deb', '/tmp/google-chrome.deb')"; \
    apt-get update; \
    apt-get install --no-install-recommends -y /tmp/google-chrome.deb; \
    rm -f /tmp/google-chrome.deb; \
    rm -rf /var/lib/apt/lists/*

ENV AUTOSURF_BROWSER_CHANNEL=chrome \
    AUTOSURF_BROWSER_EXECUTABLE_PATH=/usr/bin/google-chrome-stable
WORKDIR /app
COPY docker/entrypoint.sh /usr/local/bin/autosurf-entrypoint
COPY docker/autosurf-upgrade /usr/local/bin/autosurf-upgrade
RUN chmod 755 /usr/local/bin/autosurf-entrypoint /usr/local/bin/autosurf-upgrade \
    && mkdir /app/data /app/program /app/browser \
    && chown -R autosurf:autosurf /app
USER autosurf

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=2)"

ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/autosurf-entrypoint"]
