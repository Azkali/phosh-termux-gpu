#!/bin/bash
# Phase 5 (inside Fedora): install launch scripts, phoc.ini and the crash handler.
set -uo pipefail
cd /root
echo "[*] copy launch scripts + phoc.ini"
cp -f /tmp/phosh-gpu/launch-gpu.sh /root/launch-gpu.sh
cp -f /tmp/phosh-gpu/launch-sw.sh  /root/launch-sw.sh
cp -f /tmp/phosh-gpu/phoc.ini      /root/phoc.ini
chmod +x /root/launch-gpu.sh /root/launch-sw.sh

echo "[*] build the SIGSEGV/SIGABRT backtrace handler (used by start.sh --debug)"
cp -f /tmp/phosh-gpu/libsegcatch.c /root/libsegcatch.c
gcc -shared -fPIC -O0 -g -o /root/libsegcatch.so /root/libsegcatch.c -rdynamic \
  && echo "    built /root/libsegcatch.so" || echo "    (handler build failed - non-fatal)"

echo "[*] Phase 5 done."
