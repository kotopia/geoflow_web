#!/usr/bin/env bash
set -euo pipefail
umask 077

candidate_sha="${1:-}"
service='geoflow-stabilized.service'
expected_branch='release/stabilized-deploy'

fail() {
  echo "account_rollout_blocker=$1"
  exit 2
}

[ -n "$candidate_sha" ] || fail 'candidate_sha_missing'
command -v git >/dev/null 2>&1 || fail 'git_missing'
command -v systemctl >/dev/null 2>&1 || fail 'systemctl_missing'
command -v curl >/dev/null 2>&1 || fail 'curl_missing'
command -v sudo >/dev/null 2>&1 || fail 'sudo_missing'
sudo -n true >/dev/null 2>&1 || fail 'passwordless_sudo_required'

active="$(systemctl show "$service" -p ActiveState --value 2>/dev/null || true)"
sub="$(systemctl show "$service" -p SubState --value 2>/dev/null || true)"
[ "$active" = active ] && [ "$sub" = running ] || fail 'web_service_not_running_before_rollout'

workdir="$(systemctl show "$service" -p WorkingDirectory --value 2>/dev/null || true)"
[ -n "$workdir" ] && [ -d "$workdir" ] || fail 'service_working_directory_missing'
repo="$(git -C "$workdir" rev-parse --show-toplevel 2>/dev/null || true)"
[ -n "$repo" ] && [ -d "$repo/.git" ] || fail 'runtime_repo_missing'
[ -f "$repo/manage.py" ] || fail 'manage_py_missing'
[ -f "$repo/requirements.txt" ] || fail 'requirements_missing'
[ -f "$repo/.env" ] || fail 'runtime_dotenv_missing'

origin="$(git -C "$repo" remote get-url origin 2>/dev/null || true)"
case "$origin" in
  https://github.com/kotopia/geoflow_web|https://github.com/kotopia/geoflow_web.git|git@github.com:kotopia/geoflow_web.git) ;;
  *) fail 'unexpected_repository_origin' ;;
esac

python="$repo/.venv/bin/python"
[ -x "$python" ] || fail 'runtime_python_missing'
[ -x "$repo/.venv/bin/gunicorn" ] || fail 'runtime_gunicorn_missing'

exec_raw="$(systemctl show "$service" -p ExecStart --value 2>/dev/null || true)"
printf '%s' "$exec_raw" | grep -Fq "$repo/.venv/bin/gunicorn" || fail 'service_exec_not_stabilized_venv'
printf '%s' "$exec_raw" | grep -Fq 'geoflow_project.wsgi:application' || fail 'service_wsgi_target_unexpected'

before_code="$(curl -sS -o /dev/null -w '%{http_code}' --connect-timeout 5 --max-time 10 http://127.0.0.1:8011/ || true)"
case "$before_code" in 2??|3??) ;; *) fail 'port_8011_not_healthy_before_rollout' ;; esac

previous_sha="$(git -C "$repo" rev-parse HEAD)"
previous_branch="$(git -C "$repo" symbolic-ref --short -q HEAD || true)"
echo "account_rollout_previous_sha=$previous_sha"
echo "account_rollout_candidate_sha=$candidate_sha"

git -C "$repo" fetch --prune origin refs/heads/release/stabilized-deploy
fetched_sha="$(git -C "$repo" rev-parse FETCH_HEAD)"
[ "$fetched_sha" = "$candidate_sha" ] || fail 'candidate_sha_not_current_release_head'

backup_dir="$(mktemp -d /tmp/geoflow-account-rollout.XXXXXX)"
dirty_paths="$backup_dir/dirty-paths"
: > "$dirty_paths"
rollback_needed=0
migration_started=0

cleanup_only() {
  rm -rf "$backup_dir"
}

rollback() {
  set +e
  if [ "$rollback_needed" -eq 1 ]; then
    echo 'account_rollout_rollback_started=yes'
    git -C "$repo" reset --hard "$previous_sha" >/dev/null 2>&1 || true
    if [ -n "$previous_branch" ]; then
      git -C "$repo" checkout -B "$previous_branch" "$previous_sha" >/dev/null 2>&1 || true
    else
      git -C "$repo" checkout --detach "$previous_sha" >/dev/null 2>&1 || true
    fi
    while IFS= read -r path; do
      [ -n "$path" ] || continue
      mkdir -p "$repo/$(dirname "$path")"
      cp -p "$backup_dir/files/$path" "$repo/$path"
    done < "$dirty_paths"
    "$python" -m pip install --disable-pip-version-check --no-input -r "$repo/requirements.txt" >/dev/null 2>&1 || true
    "$python" "$repo/manage.py" collectstatic --noinput >/dev/null 2>&1 || true
    sudo -n systemctl restart "$service" >/dev/null 2>&1 || true
    sleep 3
    echo "account_rollout_rollback_service_state=$(systemctl is-active "$service" 2>/dev/null || true)"
    if [ "$migration_started" -eq 1 ]; then
      echo 'account_rollout_rollback_database_additive_migrations_retained=yes'
    fi
    echo 'account_rollout_rollback_completed=yes'
  fi
  cleanup_only
}

on_exit() {
  rc=$?
  if [ "$rc" -ne 0 ]; then
    rollback
  else
    cleanup_only
  fi
  exit "$rc"
}
trap on_exit EXIT

while IFS= read -r line; do
  [ -n "$line" ] || continue
  status="${line:0:2}"
  path="${line:3}"
  [ "$status" = ' M' ] || fail 'production_worktree_has_unreviewed_status'
  [ -f "$repo/$path" ] || fail 'dirty_path_not_regular_file'
  candidate_blob="$(git -C "$repo" rev-parse "$candidate_sha:$path" 2>/dev/null || true)"
  [ -n "$candidate_blob" ] || fail 'dirty_path_missing_from_candidate'
  working_blob="$(git -C "$repo" hash-object "$repo/$path")"
  [ "$working_blob" = "$candidate_blob" ] || fail 'production_dirty_file_diverges_from_candidate'
  printf '%s\n' "$path" >> "$dirty_paths"
  mkdir -p "$backup_dir/files/$(dirname "$path")"
  cp -p "$repo/$path" "$backup_dir/files/$path"
done < <(git -C "$repo" status --porcelain=v1)

dirty_count="$(wc -l < "$dirty_paths" | tr -d ' ')"
echo "account_rollout_reviewed_dirty_file_count=$dirty_count"
echo 'account_rollout_dirty_files_match_candidate=yes'

rollback_needed=1
git -C "$repo" checkout -B "$expected_branch" "$candidate_sha"
[ "$(git -C "$repo" rev-parse HEAD)" = "$candidate_sha" ] || fail 'candidate_checkout_failed'
[ -z "$(git -C "$repo" status --porcelain)" ] || fail 'candidate_worktree_not_clean'

"$python" -m pip install --disable-pip-version-check --no-input -r "$repo/requirements.txt"
"$python" -m pip check
"$python" "$repo/manage.py" check

cd "$repo"
DJANGO_SETTINGS_MODULE=geoflow_project.settings "$python" - <<'PY'
import django
django.setup()
from django.db import connections
from django.db.migrations.executor import MigrationExecutor

executor = MigrationExecutor(connections['default'])
applied = set(executor.loader.applied_migrations)
base = ('control', '0004_signup_verification_delivery_outbox')
target = ('control', '0006_account_password_reset_schema')
join_audit = ('control', '0005_join_request_decision_audit_columns')
allowed = {join_audit, target}
if base not in applied:
    raise SystemExit('account_rollout_blocker=required_control_0004_not_applied')
if target in applied and join_audit not in applied:
    raise SystemExit('account_rollout_blocker=invalid_control_migration_history')
plan = executor.migration_plan([target])
if any(backwards for _migration, backwards in plan):
    raise SystemExit('account_rollout_blocker=backward_migration_plan_detected')
names = {(migration.app_label, migration.name) for migration, backwards in plan if not backwards}
if not names.issubset(allowed):
    raise SystemExit('account_rollout_blocker=unexpected_migration_in_plan')
print(f'account_rollout_migration_plan_count={len(plan)}')
print('account_rollout_migration_plan_reviewed=yes')
PY

migration_started=1
"$python" manage.py migrate control 0006_account_password_reset_schema --database=default --noinput
"$python" manage.py check_account_password_reset_schema --strict
"$python" - <<'PY'
import django
django.setup()
from control.services.account_password_reset_delivery import load_account_password_reset_delivery_config
from control.services.signup_verification_runtime import load_signup_email_verification_key_ring
load_account_password_reset_delivery_config()
load_signup_email_verification_key_ring()
print('account_rollout_password_reset_runtime_config_ready=yes')
PY

"$python" manage.py collectstatic --noinput
sudo -n systemctl restart "$service"

ready=no
for _ in $(seq 1 30); do
  active="$(systemctl show "$service" -p ActiveState --value 2>/dev/null || true)"
  sub="$(systemctl show "$service" -p SubState --value 2>/dev/null || true)"
  code="$(curl -sS -o /dev/null -w '%{http_code}' --connect-timeout 2 --max-time 5 http://127.0.0.1:8011/ || true)"
  if [ "$active" = active ] && [ "$sub" = running ]; then
    case "$code" in 2??|3??) ready=yes; break ;; esac
  fi
  sleep 2
done
[ "$ready" = yes ] || fail 'service_failed_post_restart_healthcheck'

login_get="$(curl --proto '=https' -sS -o /dev/null -w '%{http_code}' --connect-timeout 5 --max-time 15 https://geoflow.co.kr/login/ || true)"
forgot_get="$(curl --proto '=https' -sS -o /dev/null -w '%{http_code}' --connect-timeout 5 --max-time 15 https://geoflow.co.kr/password/forgot/ || true)"
reset_get="$(curl --proto '=https' -sS -o /dev/null -w '%{http_code}' --connect-timeout 5 --max-time 15 https://geoflow.co.kr/password/reset/ || true)"
forgot_post="$(curl --proto '=https' -sS -o /dev/null -w '%{http_code}' --connect-timeout 5 --max-time 15 -X POST --data-urlencode 'email=probe@example.invalid' https://geoflow.co.kr/password/forgot/ || true)"
reset_post="$(curl --proto '=https' -sS -o /dev/null -w '%{http_code}' --connect-timeout 5 --max-time 15 -X POST --data-urlencode 'token=invalid-probe' https://geoflow.co.kr/password/reset/ || true)"
account_change_get="$(curl --proto '=https' -sS -o /dev/null -w '%{http_code}' --connect-timeout 5 --max-time 15 https://geoflow.co.kr/control/account/password/change/ || true)"

echo "account_rollout_login_get=$login_get"
echo "account_rollout_forgot_get=$forgot_get"
echo "account_rollout_reset_get=$reset_get"
echo "account_rollout_forgot_post_without_csrf=$forgot_post"
echo "account_rollout_reset_post_without_csrf=$reset_post"
echo "account_rollout_password_change_unauthenticated_get=$account_change_get"

[ "$login_get" = 200 ] || fail 'login_get_not_200'
[ "$forgot_get" = 200 ] || fail 'forgot_get_not_200'
[ "$reset_get" = 200 ] || fail 'reset_get_not_200'
[ "$forgot_post" = 403 ] || fail 'forgot_csrf_boundary_regressed'
[ "$reset_post" = 403 ] || fail 'reset_csrf_boundary_regressed'
case "$account_change_get" in 301|302|303|307|308) ;; *) fail 'password_change_auth_boundary_regressed' ;; esac

[ -z "$(git -C "$repo" status --porcelain)" ] || fail 'production_worktree_dirty_after_rollout'
rollback_needed=0
trap - EXIT
cleanup_only
echo "account_rollout_deployed_sha=$(git -C "$repo" rev-parse HEAD)"
echo 'account_security_production_rollout_complete=yes'
