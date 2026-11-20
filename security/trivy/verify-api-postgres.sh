#!/usr/bin/env sh
# Verify the exact scanned image against disposable PostgreSQL without runtime downloads.
set -eu
image_ref=${1:?Usage: verify-api-postgres.sh IMAGE}
network_id=""
postgres_id=""
api_id=""
cleanup() {
  if [ -n "$api_id" ]; then docker rm --force "$api_id" >/dev/null 2>&1 || true; fi
  if [ -n "$postgres_id" ]; then docker rm --force "$postgres_id" >/dev/null 2>&1 || true; fi
  if [ -n "$network_id" ]; then docker network rm "$network_id" >/dev/null 2>&1 || true; fi
}
trap cleanup EXIT HUP INT TERM
network_id=$(docker network create --internal "any674-runtime-$$")
postgres_id=$(docker run --detach --network "$network_id" --network-alias any674-postgres \
  --env POSTGRES_DB=any674_runtime --env POSTGRES_USER=anytoolai \
  --env POSTGRES_PASSWORD=any674-disposable \
  postgres:18.4-alpine3.22@sha256:774521500f4c22761b25a6bdb772a0a3c2e8dd32468210bdad9231c5752ea398)
attempt=0
until docker exec "$postgres_id" pg_isready -U anytoolai -d any674_runtime >/dev/null 2>&1; do
  attempt=$((attempt + 1))
  if [ "$attempt" -ge 60 ]; then echo "Disposable PostgreSQL did not become ready" >&2; exit 1; fi
  sleep 1
done
# These values are disposable test configuration; no production credentials are read.
set -- --network "$network_id" \
  --env APP_ENV=test --env APP_PUBLIC_BASE_URL=http://localhost:3000 \
  --env INSTANCE_TENANT_ID=anytoolai --env INSTANCE_REGION=ru \
  --env DATABASE_URL=postgresql+psycopg://anytoolai:any674-disposable@any674-postgres:5432/any674_runtime \
  --env POSTGRES_DB=any674_runtime --env POSTGRES_USER=anytoolai \
  --env POSTGRES_PASSWORD=any674-disposable --env POSTGRES_HOST=any674-postgres --env POSTGRES_PORT=5432 \
  --env CORS_ALLOW_ORIGINS=http://localhost:3000 --env SKIP_LEGAL_SEED=true \
  --env BILLING_WORKER_ENABLED=false --env OTEL_SDK_DISABLED=true
for migration in 'upgrade head' 'downgrade base' 'upgrade head'; do
  # Deliberate split of this fixed list into Alembic's action and revision.
  action=${migration%% *}
  revision=${migration#* }
  docker run --rm "$@" "$image_ref" python -m alembic -c apps/api/alembic.ini "$action" "$revision" >&2
done
api_id=$(docker run --detach --publish 127.0.0.1::8000 "$@" "$image_ref")
uid=$(docker exec "$api_id" id -u)
if [ "$uid" -eq 0 ]; then echo "API unexpectedly started as root" >&2; exit 1; fi
endpoint=$(docker port "$api_id" 8000/tcp)
attempt=0
until curl --fail --silent --show-error --max-time 2 "http://$endpoint/api/health/ready" 2>/dev/null \
  | python3 -c 'import json,sys; assert json.load(sys.stdin)["status"] == "ready"' 2>/dev/null; do
  attempt=$((attempt + 1))
  if [ "$attempt" -ge 60 ] || [ "$(docker inspect --format '{{.State.Running}}' "$api_id")" != true ]; then
    echo "API readiness failed" >&2; exit 1
  fi
  sleep 1
done
curl --fail --silent --show-error --max-time 2 "http://$endpoint/api/health/live" \
  | python3 -c 'import json,sys; assert json.load(sys.stdin)["status"] == "alive"'
immutable_id=$(docker image inspect --format '{{.Id}}' "$image_ref")
python3 -c 'import json,sys; print(json.dumps({"image_id":sys.argv[1],"uid":int(sys.argv[2]),"default_cmd":True,"liveness":"passed","readiness":"passed","postgresql":"18.4","migration_cycle":"upgrade head / downgrade base / upgrade head: passed","runtime_network":"internal Docker network; no external downloads"},indent=2))' "$immutable_id" "$uid"
