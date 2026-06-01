#!/data/data/com.termux/files/usr/bin/bash
# =============================================================================
# phosh-termux-gpu : one-shot installer  (run INSIDE the Termux app)
#
#   bash install.sh            # run all phases
#   bash install.sh 3          # run only phase 3 (and onwards)
#   PHASE_ONLY=3 bash install.sh   # run ONLY phase 3
#
# Phases:
#   1  Termux packages + Fedora (proot-distro)
#   2  Provision Fedora (phosh/phoc/mesa/fonts)
#   3  Build KGSL Turnip from Mesa main      -> /opt/mesa-kgsl-git  (slow)
#   4  Build patched wlroots 0.19            -> /root/wlroots/build (slow)
#   5  Install launch scripts into the container
# =============================================================================
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
PREFIX="${PREFIX:-/data/data/com.termux/files/usr}"
DISTRO="${DISTRO:-fedora}"
START="${1:-${PHASE_ONLY:-1}}"
ONLY="${PHASE_ONLY:-}"

GUEST_TMP="$PREFIX/tmp/phosh-gpu"   # shared into the container as /tmp/phosh-gpu

run_phase() { # n, description, command...
  local n="$1"; shift; local desc="$1"; shift
  if [ -n "$ONLY" ] && [ "$ONLY" != "$n" ]; then return; fi
  if [ "$n" -lt "$START" ]; then return; fi
  printf '\n\033[1;35m================ Phase %s: %s ================\033[0m\n' "$n" "$desc"
  "$@"
}

guest() { proot-distro login "$DISTRO" --shared-tmp -- /bin/bash "$@"; }

stage_scripts() {
  mkdir -p "$GUEST_TMP"
  cp -f "$HERE"/fedora/* "$GUEST_TMP"/
  chmod +x "$GUEST_TMP"/*.sh 2>/dev/null || true
}

phase1() { bash "$HERE/termux/1-packages.sh"; }
phase2() { stage_scripts; guest /tmp/phosh-gpu/2-provision.sh; }
phase3() { stage_scripts; guest /tmp/phosh-gpu/3-build-turnip.sh; }
phase4() { stage_scripts; guest /tmp/phosh-gpu/4-build-wlroots.sh; }
phase5() { stage_scripts; guest /tmp/phosh-gpu/5-install-runtime.sh; }

run_phase 1 "Termux packages + Fedora"        phase1
run_phase 2 "Provision Fedora"                 phase2
run_phase 3 "Build KGSL Turnip (Mesa main)"    phase3
run_phase 4 "Build patched wlroots 0.19"       phase4
run_phase 5 "Install launch scripts"           phase5

printf '\n\033[1;32mDone.\033[0m  Next:\n'
cat <<'EOF'
  1. Open Termux:X11 and set: exact resolution = your panel, Native touch,
     Stretch ON, Fullscreen ON, Adjust-resolution-on-keyboard OFF.
  2. Run:  bash start.sh        (accelerated)
        or bash start.sh --sw   (software fallback)
EOF
