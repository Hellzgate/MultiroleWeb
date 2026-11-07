# syntax=docker/dockerfile:1
#
# Multirole + web control panel  (single image, pattern A)
# --------------------------------------------------------
# base  : dyxel/multirole:v1.1.0  (Alpine/musl, linux/amd64 only)
# extra : python3 (stdlib only - no pip, no build tools)
# cmd   : our supervisor instead of ./area-zero.sh
#
# The supervisor starts ./multirole as a child, restarts it when it exits and
# serves the web panel on WEB_PORT. multirole reads config.json once, so "apply"
# means "restart the child".

FROM dyxel/multirole:v1.1.0

LABEL org.opencontainers.image.title="multirole-web" \
      org.opencontainers.image.description="Multirole game server + built-in web control panel" \
      org.opencontainers.image.version="1.0.0"

# python3 only (stdlib, no pip).
#
# The upstream image (v1.1.0) keeps a "world" entry for tcmalloc-minimal@testing, but
# the @testing repo tag no longer exists on Alpine edge, so a plain `apk add` refuses
# to commit ("Not committing changes due to missing repository tags"). multirole links
# against libtcmalloc_minimal.so.4, so it must stay installed.
#
# Upgrade-proof: tcmalloc is copied aside FIRST (whatever version upstream ships, and
# nothing at all if a future image drops it), then restored after apk. No hardcoded
# soname/version -> `FROM dyxel/multirole:vX.Y.Z` alone is enough for an upgrade.
RUN mkdir -p /tmp/_tc && cp -a /usr/lib/libtcmalloc* /tmp/_tc/ 2>/dev/null || true
RUN apk update \
 && apk add --no-cache --force-broken-world python3 tzdata
RUN cp -an /tmp/_tc/libtcmalloc* /usr/lib/ 2>/dev/null || true; rm -rf /tmp/_tc; \
 ls -l /usr/lib/libtcmalloc* 2>/dev/null || echo "no tcmalloc in base (fine)"

ENV TZ=Asia/Seoul \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    MR_BASE=/multirole \
    WEB_BIND=0.0.0.0 \
    WEB_PORT=8080 \
    MR_STOP_GRACE=10 \
    MR_RESTART_DELAY=3 \
    MR_LOG_MAX=10485760 \
    MR_LOG_KEEP=3

WORKDIR /multirole

COPY webui.py /app/webui.py
COPY App /app/App
COPY Web /app/Web

# 7911 (room hosting) / 7922 (lobby) are inherited from the base image.
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=6s --start-period=40s --retries=3 \
  CMD python3 -c "import os,sys,urllib.request;sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('WEB_PORT','8080')+'/api/health',timeout=4).status==200 else 1)"

CMD ["python3", "/app/webui.py"]
