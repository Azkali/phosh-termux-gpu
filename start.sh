#!/data/data/com.termux/files/usr/bin/bash
# Launch a phosh session. Run INSIDE Termux.
#   bash start.sh           accelerated (GPU)
#   bash start.sh --sw      software (pixman) fallback
#   bash start.sh --debug   accelerated + crash-backtrace handler (full speed)
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
DISTRO="${DISTRO:-fedora}"
MODE="${1:-}"

GUEST_SCRIPT=/root/launch-gpu.sh
ENVS=()
case "$MODE" in
  --sw)    GUEST_SCRIPT=/root/launch-sw.sh ;;
  --debug) ENVS=(-e PHOSH_GPU_DEBUG=1) ;;
esac

echo "== bringing up host display =="
bash "$HERE/termux/start-display.sh"
sleep 2

echo "== launching phosh ($GUEST_SCRIPT) =="
echo "   (switch to the Termux:X11 app to use the phone; Ctrl-C here to stop)"
exec proot-distro login "$DISTRO" --shared-tmp \
  -e DISPLAY=:0 -e PULSE_SERVER=tcp:127.0.0.1 \
  -e GALLIUM_DRIVER=virpipe -e VTEST_SOCKET_NAME=/tmp/.virgl_test \
  -e MESA_GL_VERSION_OVERRIDE=4.3 "${ENVS[@]}" \
  -- /bin/bash "$GUEST_SCRIPT"
