#!/bin/bash
# Phase 2 (inside Fedora): install the phosh shell stack + tools + fonts.
set -euo pipefail
echo "[*] dnf update"
dnf -y update 2>&1 | tail -3 || true

echo "[*] install phosh + phoc + mesa + session bits"
dnf install -y --skip-unavailable \
  phosh phoc phosh-mobile-settings \
  gnome-session gnome-settings-daemon xdg-desktop-portal-gtk xdg-desktop-portal-gnome \
  gnome-console gnome-text-editor gnome-calculator \
  mesa-dri-drivers mesa-libEGL mesa-libGL mesa-vulkan-drivers vulkan-tools \
  dbus-daemon dbus-x11 adwaita-icon-theme adwaita-cursor-theme \
  dejavu-sans-mono-fonts dejavu-sans-fonts google-noto-sans-fonts \
  wtype glib2 2>&1 | tail -4

echo "[*] Phase 2 done.  (phoc $(rpm -q --qf '%{VERSION}' phoc 2>/dev/null), links libwlroots-0.19)"
