#!/usr/bin/env bash
# Extract signed official client packages; never install packages or start a DB.
set -euo pipefail
umask 077
client_root="${1:?private client directory required}"
case "$client_root" in /*) ;; *) echo 'private_pg_client_absolute_path_required'; exit 1;; esac
[ ! -L "$client_root" ] || exit 1
mkdir -p "$client_root"
client_root="$(cd "$client_root" && pwd -P)"
if [ -x "$client_root/bin/pg_dump" ] && "$client_root/bin/pg_dump" --version >/dev/null 2>&1 && "$client_root/bin/pg_restore" --version >/dev/null 2>&1; then
  echo 'private_pg_client_ready=yes'
  exit 0
fi
. /etc/os-release
case "${ID:-}:${VERSION_CODENAME:-}" in
  ubuntu:jammy|ubuntu:noble|ubuntu:resolute|debian:bookworm|debian:trixie) ;;
  *) echo 'private_pg_client_unsupported_os'; exit 1;;
esac
arch="$(dpkg --print-architecture)"
case "$arch" in amd64|arm64) ;; *) echo 'private_pg_client_unsupported_arch'; exit 1;; esac
work="$client_root/download"
mkdir -p "$work/lists/partial" "$work/cache/archives/partial" "$work/gnupg" "$client_root/root" "$client_root/bin"
curl --proto '=https' --fail --silent --show-error --retry 3 --max-time 60 \
  https://www.postgresql.org/media/keys/ACCC4CF8.asc -o "$work/pgdg.asc"
fingerprint="$(gpg --homedir "$work/gnupg" --batch --with-colons --show-keys "$work/pgdg.asc" 2>/dev/null | awk -F: '$1=="fpr" {print $10;exit}')"
[ "$fingerprint" = 'B97B0AFCAA1A47F044F244A07FCC7D46ACCC4CF8' ] || { echo 'private_pg_client_key_mismatch'; exit 1; }
printf 'deb [arch=%s signed-by=%s] https://apt.postgresql.org/pub/repos/apt/ %s-pgdg main\n' "$arch" "$work/pgdg.asc" "$VERSION_CODENAME" > "$work/sources.list"
# Isolated lists/cache/config: no writes to /etc/apt, /usr or dpkg's database.
printf 'Dir::Etc::parts "-";\nDir::Etc::main "-";\n' > "$work/apt.conf"
opts=(-o "Dir::Etc::sourcelist=$work/sources.list" -o 'Dir::Etc::sourceparts=-'
      -o "Dir::State::lists=$work/lists" -o "Dir::Cache=$work/cache"
      -o "APT::Sandbox::User=$(id -un)" -o 'APT::Get::List-Cleanup=0')
APT_CONFIG="$work/apt.conf" apt-get "${opts[@]}" update
(
  cd "$work"
  APT_CONFIG="$work/apt.conf" apt-get "${opts[@]}" download postgresql-client-16 libpq5
  for package in ./*.deb; do dpkg-deb --extract "$package" "$client_root/root"; done
)
# Resolve the package's architecture-specific libpq location without guessing it.
private_lib="$(find "$client_root/root/usr/lib" -name libpq.so.5 -printf '%h\n' | head -1)"
[ -n "$private_lib" ] || { echo 'private_pg_client_library_missing'; exit 1; }
for tool in pg_dump pg_restore; do
  target="$client_root/root/usr/lib/postgresql/16/bin/$tool"
  [ -x "$target" ] || exit 1
  # %q safely quotes local paths. Credentials are inherited only at execution.
  printf '#!/usr/bin/env bash\nexport LD_LIBRARY_PATH=%q\nexec %q "$@"\n' "$private_lib" "$target" > "$client_root/bin/$tool"
  chmod 700 "$client_root/bin/$tool"
  "$client_root/bin/$tool" --version
 done
echo 'private_pg_client_ready=yes'
