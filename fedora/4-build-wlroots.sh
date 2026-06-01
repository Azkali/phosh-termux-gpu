#!/bin/bash
# Phase 4 (inside Fedora): build the patched wlroots 0.19 -> /root/wlroots/build
# phoc links libwlroots-0.19.so dynamically, so we just LD_LIBRARY_PATH the
# rebuilt lib at launch -- no phoc rebuild. ~3-5 min.
set -uo pipefail
cd /root

echo "[*] clone wlroots 0.19"
[ -d wlroots ] || git clone --depth 1 -b 0.19 https://gitlab.freedesktop.org/wlroots/wlroots.git
cd wlroots
echo "    $(grep -m1 'version' meson.build)"

echo "[*] build deps"
dnf install -y --skip-unavailable \
  meson ninja-build gcc gcc-c++ pkgconf-pkg-config glslang \
  wayland-devel wayland-protocols-devel libdrm-devel libinput-devel \
  libxkbcommon-devel pixman-devel vulkan-headers vulkan-loader-devel \
  libxcb-devel xcb-util-devel xcb-util-wm-devel xcb-util-image-devel \
  xcb-util-errors-devel xcb-util-renderutil-devel xcb-util-cursor-devel \
  libdisplay-info-devel hwdata-devel libseat-devel ffmpeg-free-devel \
  mesa-libEGL-devel mesa-libgbm-devel mesa-libGLES-devel libliftoff-devel \
  lcms2-devel xorg-x11-server-Xwayland xorg-x11-server-Xwayland-devel 2>&1 | tail -3

echo "[*] apply patches (idempotent: restore pristine, then apply)"
for f in render/vulkan/vulkan.c render/vulkan/renderer.c render/vulkan/pass.c \
         include/render/vulkan.h render/wlr_renderer.c render/vulkan/pixel_format.c \
         render/vulkan/texture.c types/wlr_layer_shell_v1.c; do
  [ -f "$f.orig" ] || cp "$f" "$f.orig"
  cp "$f.orig" "$f"
done
python3 /tmp/phosh-gpu/apply_wlr_patches.py

echo "[*] configure + build (full backends/renderers to ABI-match phoc)"
[ -f build/build.ninja ] || meson setup build \
  -Dbackends=drm,libinput,x11 -Drenderers=gles2,vulkan -Dxwayland=enabled \
  -Dexamples=false -Dwerror=false --prefix=/usr 2>&1 | tail -3
ninja -C build 2>&1 | tail -4
ls -la build/libwlroots-0.19.so

echo "[*] ABI sanity (want phoc usage text, NOT 'undefined symbol'):"
LD_LIBRARY_PATH=/root/wlroots/build phoc --help 2>&1 | head -2
echo "[*] Phase 4 done -> /root/wlroots/build/libwlroots-0.19.so"
