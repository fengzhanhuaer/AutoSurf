FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    AUTOSURF_REPOSITORY=https://github.com/fengzhanhuaer/AutoSurf.git \
    AUTOSURF_BRANCH=main

RUN apt-get update \
    && apt-get install --no-install-recommends -y git tini \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 autosurf
WORKDIR /app
COPY docker/entrypoint.sh /usr/local/bin/autosurf-entrypoint
COPY docker/autosurf-upgrade /usr/local/bin/autosurf-upgrade
RUN chmod 755 /usr/local/bin/autosurf-entrypoint /usr/local/bin/autosurf-upgrade \
    && mkdir /app/data /app/program \
    && chown -R autosurf:autosurf /app
USER autosurf

VOLUME ["/app/data", "/app/program"]
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=2)"

ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/autosurf-entrypoint"]
