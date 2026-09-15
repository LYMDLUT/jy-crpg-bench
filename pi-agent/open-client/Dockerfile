FROM node:24.7.0-bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
      python3 python3-numpy python3-pil python3-opencv curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/pi
COPY package.json package-lock.json ./
RUN npm ci --omit=dev && npm cache clean --force
COPY qunxia ./extensions/qunxia
COPY bridge.mjs ./bridge.mjs

# This image contains the client runtime only, never the repository or game.
USER node
WORKDIR /client/workspace
ENTRYPOINT ["node", "/opt/pi/bridge.mjs"]
