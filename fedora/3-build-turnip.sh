#!/bin/bash
# Phase 3 (inside Fedora): build a KGSL Turnip from Mesa main -> /opt/mesa-kgsl-git
# Mesa main already has native Adreno 830 (chip_id 0x44050001) + UBWC 5.0, so the
# only source change needed is dropping the KHR_display guard (so vulkaninfo works).
# ~15-25 min on 8 cores.
set -uo pipefail
PREFIX_OUT=/opt/mesa-kgsl-git
cd /root

echo "[*] clone mesa main (shallow)"
[ -d mesa-git ] || git clone --depth 1 https://gitlab.freedesktop.org/mesa/mesa.git mesa-git
cd mesa-git
echo "    $(git log -1 --format='%h %ci' 2>/dev/null)"

echo "[*] build deps"
dnf builddep -y mesa 2>&1 | tail -2
dnf install -y --skip-unavailable meson ninja-build glslang python3-mako python3-pyyaml 2>&1 | tail -1

echo "[*] patch: drop KHR_display guard in the KGSL backend (keep a830/UBWC5 = native)"
git checkout src/freedreno/vulkan/tu_knl_kgsl.cc 2>/dev/null || true
python3 - <<'PY'
f='src/freedreno/vulkan/tu_knl_kgsl.cc'
import os
if os.path.exists(f):
    s=open(f).read()
    g=('   if (instance->vk.enabled_extensions.KHR_display) {\n'
       '      return vk_errorf(instance, VK_ERROR_INITIALIZATION_FAILED,\n'
       '                       "I can\'t KHR_display");\n   }')
    if g in s:
        open(f,'w').write(s.replace(g,'   /* KGSL: ignore KHR_display instead of failing. */',1))
        print('   patched KHR_display guard')
    else:
        print('   KHR_display guard not present (already fixed upstream) - ok')
PY

echo "[*] configure + build (turnip only, KGSL kmd)"
rm -rf builddir
meson setup builddir --prefix="$PREFIX_OUT" -Dbuildtype=release \
  -Dvulkan-drivers=freedreno -Dgallium-drivers= -Dfreedreno-kmds=kgsl,msm \
  -Dplatforms=x11,wayland -Dglx=disabled -Degl=disabled -Dgbm=disabled \
  -Dopengl=false -Dllvm=disabled -Dvideo-codecs= -Dvulkan-layers= 2>&1 | tail -4
ninja -C builddir 2>&1 | tail -4
ninja -C builddir install 2>&1 | tail -2

ICD="$PREFIX_OUT/share/vulkan/icd.d/freedreno_icd.aarch64.json"
echo "[*] verify (want 'Adreno (TM) 830'):"
XDG_RUNTIME_DIR=/tmp VK_ICD_FILENAMES="$ICD" vulkaninfo --summary 2>&1 \
  | grep -iE 'deviceName|driverID|apiVersion|driverInfo' | head
echo "[*] Phase 3 done -> $ICD"
