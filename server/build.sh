#!/bin/sh
# Build the shared library the Python server loads. Linux/x86_64.
set -e
cd "$(dirname "$0")"
gcc -O2 -fPIC -shared -pthread \
  -I../Sources/CoreHost/include \
  ../Sources/CoreHost/CoreHost.c tiles.c \
  -o libqunxia.so -ldl -lpthread
echo "built $(pwd)/libqunxia.so"
