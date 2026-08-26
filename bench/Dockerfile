# Benchmark broker: game, renderer and catalogue in one image.
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential ca-certificates curl ffmpeg unzip \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY Sources/CoreHost /app/Sources/CoreHost
COPY server /app/server
COPY bench /app/bench
COPY skills /app/skills
COPY assets/game-data.tar.gz /app/assets/game-data.tar.gz

# the emulator core, and the shared library the server loads
RUN mkdir -p /app/cores && cd /app/cores \
 && curl -sSLo core.zip https://buildbot.libretro.com/nightly/linux/x86_64/latest/dosbox_pure_libretro.so.zip \
 && unzip -oq core.zip && rm core.zip
RUN sh /app/server/build.sh
RUN tar xzf /app/assets/game-data.tar.gz -C /app && rm /app/assets/game-data.tar.gz

RUN pip install --no-cache-dir aiohttp pillow numpy google-cloud-storage

# gcloud, for publishing videos and the catalogue to the bucket
RUN curl -sSL https://dl.google.com/dl/cloudsdk/channels/rapid/downloads/google-cloud-cli-linux-x86_64.tar.gz       -o /tmp/gcloud.tgz  && tar xzf /tmp/gcloud.tgz -C /opt && rm /tmp/gcloud.tgz  && /opt/google-cloud-sdk/install.sh -q --path-update=false --usage-reporting=false
ENV PATH="/opt/google-cloud-sdk/bin:${PATH}"

ENV QUNXIA_PYTHON=/usr/local/bin/python \
    QUNXIA_CORE=/app/cores/dosbox_pure_libretro.so \
    QUNXIA_GAME=/app/game/PLAY.BAT \
    QUNXIA_START_STATE=/app/saves/start.state \
    QUNXIA_VIDEO_DIR=/app/videos \
    QUNXIA_CATALOG=/app/videos/catalog.json \
    PYTHONPATH=/app/bench \
    PYTHONUNBUFFERED=1 \
    PORT=8080
EXPOSE 8080
CMD ["python", "/app/bench/broker.py"]
