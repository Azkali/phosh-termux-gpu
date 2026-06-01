#!/data/data/com.termux/files/usr/bin/bash
# Stop the phosh session (and optionally the host display).
DISTRO="${DISTRO:-fedora}"
proot-distro login "$DISTRO" -- /bin/bash -c \
  'pkill -9 -f "phoc -S"; pkill -9 -f libexec/phosh; pkill -9 -f dbus-run-session' 2>/dev/null
echo "phosh stopped. (X server left running; 'pkill -f com.termux.x11' to stop it too)"
