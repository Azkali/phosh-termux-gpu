#!/data/data/com.termux/files/usr/bin/bash
# Phase 1 (Termux side): packages + Fedora container.
set -euo pipefail
DISTRO="${DISTRO:-fedora}"

echo "[*] Termux packages"
pkg update -y
pkg install -y x11-repo
pkg install -y \
  proot-distro git termux-x11-nightly virglrenderer-android \
  mesa-vulkan-icd-freedreno vulkan-tools vulkan-loader-generic \
  pulseaudio termux-am which

echo "[*] /dev/kgsl-3d0 check (must be crw-rw-rw- for rootless Turnip)"
ls -l /dev/kgsl-3d0 || echo "  WARNING: /dev/kgsl-3d0 not visible — GPU Vulkan will not work."

echo "[*] Installing Fedora container (if missing)"
if ! proot-distro list 2>/dev/null | grep -q "^${DISTRO}\b.*installed" \
   && [ ! -d "$PREFIX/var/lib/proot-distro/installed-rootfs/${DISTRO}" ]; then
  proot-distro install "$DISTRO"
else
  echo "  $DISTRO already installed."
fi

echo "[*] Phase 1 done."
