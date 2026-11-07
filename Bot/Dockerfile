# 봇 컨테이너 (Mono + WindBot + 컨트롤러)
#
# mono:6.12 는 Debian **buster**(EOL) 기반이라 기본 apt 저장소가 404 다.
# → archive.debian.org 로 바꿔서 python3-minimal 만 설치한다.
#
# 빌드:  docker build -f Bot/Dockerfile -t multirole-bot:1.0.0 Bot
FROM mono:6.12

RUN set -eux; \
    if [ -f /etc/apt/sources.list ]; then \
      sed -i -E 's|https?://deb\.debian\.org/debian-security|http://archive.debian.org/debian-security|g; s|https?://deb\.debian\.org/debian|http://archive.debian.org/debian|g; /buster-updates/d' /etc/apt/sources.list; \
    fi; \
    apt-get -o Acquire::Check-Valid-Until=false update; \
    apt-get install -y --no-install-recommends python3;   # minimal 은 json/urllib 가 빠진다 \
    rm -rf /var/lib/apt/lists/*

ENV MR_BOT_DIR=/bot \
    MR_BOT_DB_GLOB=/db/*.cdb \
    MR_BOT_PORT=7930 \
    MR_FRONT_PORT=7914 \
    MR_LIST_PORT=7922 \
    MR_BOT_MAX=2

WORKDIR /bot
COPY botd.py /bot/botd.py

EXPOSE 7930
CMD ["python3", "/bot/botd.py"]