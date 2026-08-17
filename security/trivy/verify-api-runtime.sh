#!/usr/bin/env sh
set -eu

image_ref=${1:?Usage: verify-api-runtime.sh IMAGE}

configured_user=$(docker image inspect --format '{{.Config.User}}' "$image_ref")
if [ "$configured_user" != "app" ]; then
  echo "Expected runtime user app, got: $configured_user" >&2
  exit 1
fi

docker run --rm --entrypoint sh "$image_ref" -ec '
  resolved_uid=$(id -u)
  if [ "$resolved_uid" -eq 0 ]; then
    echo "Expected runtime user app to resolve to a non-root UID, got: $resolved_uid" >&2
    exit 1
  fi

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

container_id=$(docker run --detach --publish 127.0.0.1::8000 \
  --env APP_ENV=test \
  --env APP_PUBLIC_BASE_URL=http://localhost:3000 \
  --env DATABASE_URL=sqlite+pysqlite:///:memory: \
  --env POSTGRES_DB=anytoolai_test \
  --env POSTGRES_USER=anytoolai \
  --env POSTGRES_PASSWORD=anytoolai \
  --env POSTGRES_HOST=postgres \
  --env POSTGRES_PORT=5432 \
  --env CLOUDPAYMENTS_ENABLED=false \
  --env CORS_ALLOW_ORIGINS=http://localhost:3000 \
  --env SKIP_LEGAL_SEED=true \
  --env OTEL_SDK_DISABLED=true \
  "$image_ref" \
  python -m uvicorn app.main:app --app-dir apps/api \
  --host 0.0.0.0 --port 8000 --proxy-headers \
  --forwarded-allow-ips 127.0.0.1 --log-level warning)

endpoint=$(docker port "$container_id" 8000/tcp)
response=""
attempt=0
while [ "$attempt" -lt 50 ]; do
  if response=$(curl --connect-timeout 1 --max-time 2 \
    --fail --silent --show-error "http://${endpoint}/health/live" 2>/dev/null); then
    break
  fi
  if [ "$(docker inspect --format '{{.State.Running}}' "$container_id")" != "true" ]; then
    docker logs "$container_id" >&2
    exit 1
  fi
  attempt=$((attempt + 1))
  sleep 0.2
done

if [ "$response" != '{"status":"ok"}' ]; then
  docker logs "$container_id" >&2
  echo "Unexpected liveness response: $response" >&2
  exit 1
fi

echo "Verified patched, non-root API production image liveness."
