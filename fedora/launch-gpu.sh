#!/bin/bash
# Accelerated phosh session: patched wlroots Vulkan renderer on KGSL Turnip,
# presenting to Termux:X11 over XShm.  Run from inside the Fedora container.
# Env knobs:
#   PHOSH_GPU_DEBUG=1   LD_PRELOAD the SIGSEGV/SIGABRT backtrace handler + full speed
#   PHOSH_GPU_TU_DEBUG  override TU_DEBUG (default is chosen per GPU generation below)
set -u
export XDG_RUNTIME_DIR=/tmp/runtime-root
mkdir -p "$XDG_RUNTIME_DIR"; chmod 700 "$XDG_RUNTIME_DIR"
export XDG_SESSION_TYPE=wayland XDG_CURRENT_DESKTOP=Phosh:GNOME
export DISPLAY="${DISPLAY:-:0}"
export WLR_BACKEND=x11 WLR_X11_OUTPUTS=1 WLR_NO_HARDWARE_CURSORS=1
export GDK_BACKEND=wayland QT_QPA_PLATFORM=wayland

# Force GTK4 apps to software (cairo) rendering: the compositor has no DMA-BUF,
# so GTK4's default GPU path (GSK Vulkan/GL) crashes apps (e.g. Console). Cairo
# submits shm buffers that phoc still composites on the GPU.
export GSK_RENDERER=cairo

# --- GPU compositor: patched wlroots + Mesa-main Turnip on /dev/kgsl-3d0 ---
export LD_LIBRARY_PATH=/root/wlroots/build
export WLR_RENDERER=vulkan
export VK_ICD_FILENAMES=/opt/mesa-kgsl-git/share/vulkan/icd.d/freedreno_icd.aarch64.json

# Per-GPU TU_DEBUG default. The brand-new Adreno 8xx (e.g. 830) Turnip has a rare
# post-unlock race that serializing GPU submission (flushall,syncdraw) tames; the
# mature 7xx and earlier (e.g. 750/740) don't need it and run faster without it.
# proot binds the host /sys, so we can read the model straight from KGSL.
# Override anytime with PHOSH_GPU_TU_DEBUG=... (empty string = full speed).
gpu_model="$(cat /sys/class/kgsl/kgsl-3d0/gpu_model 2>/dev/null)"   # e.g. "Adreno750v2"
adreno_gen="$(printf '%s' "$gpu_model" | grep -oE '[0-9]' | head -1)"  # leading digit: 8, 7, ...
case "$adreno_gen" in
  3|4|5|6|7) tu_default="" ;;             # a7xx and older: mature, full speed
  *)         tu_default="flushall,syncdraw" ;;  # a8xx+ OR undetected: serialize (the safe default)
esac
export TU_DEBUG="${PHOSH_GPU_TU_DEBUG-$tu_default}"
echo "[guest] GPU: ${gpu_model:-unknown} -> TU_DEBUG='${TU_DEBUG}'"

if [ "${PHOSH_GPU_DEBUG:-0}" = "1" ]; then
  export LD_PRELOAD=/root/libsegcatch.so      # backtrace on crash
  export TU_DEBUG=""                            # full speed so the race actually shows
  echo "[guest] GPU compositor (DEBUG: backtrace handler, full speed)"
else
  echo "[guest] GPU compositor: wlroots Vulkan (Mesa-main Turnip/KGSL) + XShm (TU_DEBUG=$TU_DEBUG)"
fi

exec dbus-run-session -- bash -c '
  gsettings set sm.puri.phosh.lockscreen require-unlock false 2>/dev/null || true
  gsettings set org.gnome.desktop.screensaver lock-enabled false 2>/dev/null || true
  gsettings set org.gnome.desktop.background primary-color "#1a5fb4" 2>/dev/null || true
  gsettings set org.gnome.desktop.background color-shading-type solid 2>/dev/null || true
  gsettings set org.gnome.desktop.interface monospace-font-name "DejaVu Sans Mono 11" 2>/dev/null || true
  rm -f "$XDG_RUNTIME_DIR"/wayland-0 "$XDG_RUNTIME_DIR"/wayland-0.lock 2>/dev/null
  # auto-dismiss the lock screen (X11 backend has no touch; send Enter over the
  # wayland virtual keyboard for a while)
  ( sleep 5; for i in $(seq 1 12); do WAYLAND_DISPLAY=wayland-0 wtype -k Return 2>/dev/null; sleep 1.5; done ) &
  exec phoc -S --socket wayland-0 -C /root/phoc.ini -E /usr/libexec/phosh
'
