#!/usr/bin/env bash
# CI-only: use Ubuntu's official HTTPS archive while retaining apt signatures.
set -euo pipefail
for mirror_list in /etc/apt/apt-mirrors.txt /etc/apt/apt-mirrors-security.txt /etc/apt/sources.list /etc/apt/sources.list.d/*.list /etc/apt/sources.list.d/*.sources; do
  if [ -f "$mirror_list" ]; then
    sudo sed -Ei 's#http://(azure\.archive\.ubuntu\.com|[a-z0-9-]+\.ec2\.archive\.ubuntu\.com)/ubuntu#https://archive.ubuntu.com/ubuntu#g' "$mirror_list"
  fi
done
