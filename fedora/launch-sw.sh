#!/bin/bash
# Software (pixman) phosh session — no GPU, rock-solid fallback.
set -u
export XDG_RUNTIME_DIR=/tmp/runtime-root
mkdir -p "$XDG_RUNTIME_DIR"; chmod 700 "$XDG_RUNTIME_DIR"
export XDG_SESSION_TYPE=wayland XDG_CURRENT_DESKTOP=Phosh:GNOME
export DISPLAY="${DISPLAY:-:0}"
export WLR_BACKEND=x11 WLR_X11_OUTPUTS=1 WLR_NO_HARDWARE_CURSORS=1
export GDK_BACKEND=wayland QT_QPA_PLATFORM=wayland
export WLR_RENDERER=pixman GSK_RENDERER=cairo LIBGL_ALWAYS_SOFTWARE=1
echo "[guest] SOFTWARE compositor (pixman)"
exec dbus-run-session -- bash -c '
  gsettings set sm.puri.phosh.lockscreen require-unlock false 2>/dev/null || true
  gsettings set org.gnome.desktop.screensaver lock-enabled false 2>/dev/null || true
  gsettings set org.gnome.desktop.background primary-color "#1a5fb4" 2>/dev/null || true
  gsettings set org.gnome.desktop.background color-shading-type solid 2>/dev/null || true
  gsettings set org.gnome.desktop.interface monospace-font-name "DejaVu Sans Mono 11" 2>/dev/null || true
  gsettings set org.gnome.desktop.interface enable-animations false 2>/dev/null || true
  rm -f "$XDG_RUNTIME_DIR"/wayland-0 "$XDG_RUNTIME_DIR"/wayland-0.lock 2>/dev/null
  ( sleep 5; for i in $(seq 1 12); do WAYLAND_DISPLAY=wayland-0 wtype -k Return 2>/dev/null; sleep 1.5; done ) &
  exec phoc -S --socket wayland-0 -C /root/phoc.ini -E /usr/libexec/phosh
'
