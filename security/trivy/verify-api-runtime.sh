#!/usr/bin/env sh
set -eu

image_ref=${1:?Usage: verify-api-runtime.sh IMAGE}

configured_user=$(docker image inspect --format '{{.Config.User}}' "$image_ref")
if [ "$configured_user" != "app" ]; then
  echo "Expected runtime user app, got: $configured_user" >&2
  exit 1
fi

docker run --rm --network none --entrypoint sh "$image_ref" -ec '
  resolved_uid=$(id -u)
  if [ "$resolved_uid" -eq 0 ]; then
    echo "Expected runtime user app to resolve to a non-root UID, got: $resolved_uid" >&2
    exit 1
  fi

  # Build/account/mount tools are removed only from the production target.
  for tool in apt apt-get adduser useradd groupadd passwd mount umount; do
    if command -v "$tool" >/dev/null 2>&1; then
      echo "Unexpected production runtime tool: $tool" >&2
      exit 1
    fi
  done
  for package in apt libapt-pkg7.0 adduser passwd mount; do
    if dpkg-query -s "$package" 2>/dev/null | grep -q "^Status: install ok installed$"; then
      echo "Unexpected production runtime package: $package" >&2
      exit 1
    fi
  done
  audit=$(dpkg --audit)
  if [ -n "$audit" ]; then
    echo "Production package audit failed" >&2
    exit 1
  fi
  # Official python:slim already omits optional GUI Tk/Tcl dependencies.
  native_files=$(find /opt/api-venv /usr/local/lib/python3.12/lib-dynload -type f -name "*.so" ! -name "_tkinter*")
  while IFS= read -r library; do
    [ -n "$library" ] || continue
    dependencies=$(ldd "$library") || {
      echo "Production native dependency inspection failed: $library" >&2
      exit 1
    }
    case "$dependencies" in
      *"not found"*)
        echo "Production native shared-library dependency missing: $library" >&2
        exit 1
        ;;
    esac
  done <<EOF
$native_files
EOF
  python -c "
import bz2, ctypes, curses, greenlet, lzma, readline, sqlite3, ssl, uuid, zlib
from zoneinfo import ZoneInfo
assert ssl.create_default_context().get_ca_certs()
assert ZoneInfo(\"Europe/Moscow\")
for codec in (bz2, lzma, zlib):
    assert codec.decompress(codec.compress(b\"runtime\")) == b\"runtime\"
assert sqlite3.connect(\":memory:\").execute(\"select 1\").fetchone() == (1,)
"

  set -- $(dpkg-query -W util-linux)
  installed=$2
  if ! dpkg --compare-versions "$installed" ge "2.41.5-0+deb13u1"; then
    echo "Expected util-linux >= 2.41.5-0+deb13u1, got: $installed" >&2
    exit 1
  fi
'

container_id=""
cleanup() {
  if [ -n "$container_id" ]; then
    docker rm --force "$container_id" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT HUP INT TERM

# Prepare a disposable schema for startup policy initialization. PostgreSQL
# migrations are verified separately by the production gate.
container_id=$(docker run --detach --publish 127.0.0.1::8000 \
  --env APP_ENV=test \
  --env APP_PUBLIC_BASE_URL=http://localhost:3000 \
  --env INSTANCE_TENANT_ID=anytoolai \
  --env INSTANCE_REGION=ru \
  --env DATABASE_URL=sqlite+pysqlite:////tmp/api-runtime-smoke.db \
  --env POSTGRES_DB=anytoolai_test \
  --env POSTGRES_USER=anytoolai \
  --env POSTGRES_PASSWORD=anytoolai \
  --env POSTGRES_HOST=postgres \
  --env POSTGRES_PORT=5432 \
  --env CORS_ALLOW_ORIGINS=http://localhost:3000 \
  --env SKIP_LEGAL_SEED=true \
  --env BILLING_WORKER_ENABLED=false \
  --env OTEL_SDK_DISABLED=true \
  "$image_ref" sh -ec '
    PYTHONPATH=apps/api python -c "import app.models; from app.core.database import Base, engine; Base.metadata.create_all(engine)"
    exec python -m uvicorn app.main:app --app-dir apps/api \
      --host 0.0.0.0 --port 8000 --proxy-headers \
      --forwarded-allow-ips 127.0.0.1 --no-access-log --log-level warning
  ')

endpoint=$(docker port "$container_id" 8000/tcp)
response=""
attempt=0
while [ "$attempt" -lt 150 ]; do
  if response=$(curl --connect-timeout 1 --max-time 2 \
    --fail --silent --show-error "http://${endpoint}/api/health/live" 2>/dev/null); then
    break
  fi
  if [ "$(docker inspect --format '{{.State.Running}}' "$container_id")" != "true" ]; then
    docker logs "$container_id" >&2
    exit 1
  fi
  attempt=$((attempt + 1))
  sleep 0.2
done

if [ "$response" != '{"status":"alive"}' ]; then
  docker logs "$container_id" >&2
  echo "Unexpected liveness response: $response" >&2
  exit 1
fi

echo "Verified minimized, non-root API runtime libraries and liveness."
