#!/bin/sh
# Build the shared library the Python server loads. Linux or macOS.
set -e
cd "$(dirname "$0")"
case "$(uname -s)" in
  Darwin) SHARED="-dynamiclib" ;;
  *)      SHARED="-shared" ;;
esac
cc -O2 -fPIC $SHARED -pthread \
  -I../Sources/CoreHost/include \
  ../Sources/CoreHost/CoreHost.c tiles.c \
  -o libqunxia.so -ldl -lpthread
echo "built $(pwd)/libqunxia.so"
