#!/data/data/com.termux/files/usr/bin/bash
# Start the Termux:X11 server, the virgl GL bridge and PulseAudio (host side).
# Safe to re-run; it restarts the X server (fixes the "stale black screen").
export PREFIX="${PREFIX:-/data/data/com.termux/files/usr}"
export HOME="${HOME:-/data/data/com.termux/files/home}"
export TMPDIR="${TMPDIR:-$PREFIX/tmp}"
export PATH="$PREFIX/bin:$PATH"
mkdir -p "$TMPDIR"

echo "[*] stopping any old X11/virgl"
pkill -f 'com.termux.x11' 2>/dev/null
pkill -f virgl_test_server_android 2>/dev/null
sleep 1

echo "[*] PulseAudio (TCP loopback for the guest)"
pulseaudio --start --exit-idle-time=-1 2>/dev/null
pactl load-module module-native-protocol-tcp auth-ip-acl=127.0.0.1 auth-anonymous=1 2>/dev/null || true

echo "[*] Termux:X11 server on :0"
nohup termux-x11 :0 -ac >"$TMPDIR/x11.log" 2>&1 &
sleep 3

echo "[*] virgl GL server (native Adreno GLES; LD_LIBRARY_PATH must be unset)"
rm -f "$TMPDIR/.virgl_test"
env -u LD_LIBRARY_PATH nohup virgl_test_server_android --socket-path "$TMPDIR/.virgl_test" \
  >"$TMPDIR/virgl.log" 2>&1 &
sleep 1

echo "[*] foreground the Termux:X11 activity"
am start -n com.termux.x11/.MainActivity >/dev/null 2>&1 || \
  termux-am start -n com.termux.x11/.MainActivity >/dev/null 2>&1 || true
echo "[*] host display up."
