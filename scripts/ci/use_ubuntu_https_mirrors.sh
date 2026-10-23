#!/usr/bin/env bash
# GitHub Ubuntu runners can throttle large GDAL/font packages on the Azure HTTP
# mirror. Use Ubuntu's official HTTPS archive, retaining apt signature checks.
# CI-only: do not invoke on a production host.
set -euo pipefail
for mirror_list in /etc/apt/apt-mirrors.txt /etc/apt/apt-mirrors-security.txt; do
  if [ -f "$mirror_list" ]; then
    sudo sed -i 's|http://azure.archive.ubuntu.com/ubuntu|https://archive.ubuntu.com/ubuntu|g' "$mirror_list"
  fi
done
