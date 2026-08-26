# Benchmark backend: the game, the renderer, and the publisher in one image.
# Videos and the catalogue go to the bucket through the Python client, which
# reads the service account off the metadata server, so the gcloud CLI (and the
# ~350MB it costs) is not installed.
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

ENV QUNXIA_PYTHON=/usr/local/bin/python \
    QUNXIA_CORE=/app/cores/dosbox_pure_libretro.so \
    QUNXIA_GAME=/app/game/PLAY.BAT \
    QUNXIA_START_STATE=/app/saves/start.state \
    QUNXIA_VIDEO_DIR=/app/videos \
    QUNXIA_RESULT_DIR=/app/videos/results \
    QUNXIA_CATALOG=/app/videos/catalog.json \
    PYTHONPATH=/app/bench \
    PYTHONUNBUFFERED=1 \
    PORT=8080
EXPOSE 8080
CMD ["python", "/app/bench/broker.py"]
