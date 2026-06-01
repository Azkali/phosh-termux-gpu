# Manual / per-phase install

`install.sh` just runs these in order. If a phase fails, fix it and re-run from
that phase:

```bash
bash install.sh 3            # re-run from phase 3 onward
PHASE_ONLY=4 bash install.sh # re-run ONLY phase 4
```

| Phase | Where | Script | Notes |
|------:|-------|--------|-------|
| 1 | Termux | `termux/1-packages.sh` | Termux pkgs + `proot-distro install fedora`. |
| 2 | Fedora | `fedora/2-provision.sh` | phosh/phoc/mesa/fonts. |
| 3 | Fedora | `fedora/3-build-turnip.sh` | Mesa-main Turnip → `/opt/mesa-kgsl-git` (~15-25 min). |
| 4 | Fedora | `fedora/4-build-wlroots.sh` | patched wlroots → `/root/wlroots/build` (~3-5 min). |
| 5 | Fedora | `fedora/5-install-runtime.sh` | launch scripts + `phoc.ini` + crash handler. |

To run a Fedora-side phase by hand:

```bash
mkdir -p $PREFIX/tmp/phosh-gpu && cp fedora/* $PREFIX/tmp/phosh-gpu/
proot-distro login fedora --shared-tmp -- bash /tmp/phosh-gpu/3-build-turnip.sh
```

## Verifying each piece

```bash
# Turnip enumerates on the Adreno (inside Fedora):
proot-distro login fedora -- bash -c \
 'VK_ICD_FILENAMES=/opt/mesa-kgsl-git/share/vulkan/icd.d/freedreno_icd.aarch64.json \
  XDG_RUNTIME_DIR=/tmp vulkaninfo --summary | grep -iE "deviceName|driverID"'
# -> Adreno (TM) 830 / DRIVER_ID_MESA_TURNIP

# phoc loads the patched wlroots without missing symbols:
proot-distro login fedora -- bash -c \
 'LD_LIBRARY_PATH=/root/wlroots/build phoc --help | head -2'
```

## Adapting to other devices

- Edit `fedora/phoc.ini` `mode =` to your panel resolution.
- Other recent Adreno (a7xx/a8xx) should "just work" on Mesa main; older ones may
  need the explicit device-id / UBWC patches (see `docs/ARCHITECTURE.md`).
- `/dev/kgsl-3d0` must be `crw-rw-rw-` (it is on the tested device, no root).
