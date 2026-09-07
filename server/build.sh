#!/bin/sh
# Build without overwriting a library that a live process has mapped.
set -e
cd "$(dirname "$0")"
case "$(uname -s)" in
  Darwin) SHARED="-dynamiclib"; DL_LIBS="" ;;
  *) SHARED="-shared"; DL_LIBS="-ldl" ;;
esac
OUTPUT="libqunxia.so.build.$$"
trap 'rm -f "$OUTPUT"' EXIT HUP INT TERM
cc -std=c11 -O2 -fPIC "$SHARED" -pthread \
  -I../Sources/CoreHost/include \
  ../Sources/CoreHost/CoreHost.c tiles.c \
  -o "$OUTPUT" $DL_LIBS -lpthread
mv -f "$OUTPUT" libqunxia.so
echo "built $(pwd)/libqunxia.so"
