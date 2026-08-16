#!/usr/bin/env sh
set -eu

image_ref=${1:?Usage: verify-web-runtime.sh IMAGE}
expected_command='["node","apps/web/server.js"]'

configured_user=$(docker image inspect --format '{{.Config.User}}' "$image_ref")
configured_command=$(docker image inspect --format '{{json .Config.Cmd}}' "$image_ref")

if [ "$configured_user" != "node" ]; then
  echo "Expected runtime user node, got: $configured_user" >&2
  exit 1
fi

if [ "$configured_command" != "$expected_command" ]; then
  echo "Expected runtime command $expected_command, got: $configured_command" >&2
  exit 1
fi

docker run --rm --entrypoint sh "$image_ref" -ec '
  test "$(id -u)" -ne 0
  test "$(node --version)" = "v24.18.0"

  for path in \
    /usr/local/bin/corepack \
    /usr/local/bin/npm \
    /usr/local/bin/npx \
    /usr/local/lib/node_modules/corepack \
    /usr/local/lib/node_modules/npm \
    /app/node_modules/vitest \
    /app/node_modules/vite \
    /app/node_modules/@vitejs \
    /app/node_modules/@vitest \
    /app/node_modules/esbuild \
    /app/apps/web/node_modules/vitest \
    /app/apps/web/node_modules/vite \
    /app/apps/web/node_modules/@vitejs \
    /app/apps/web/node_modules/@vitest \
    /app/apps/web/node_modules/esbuild
  do
    if [ -e "$path" ] || [ -L "$path" ]; then
      echo "Unexpected runtime path: $path" >&2
      exit 1
    fi
  done
'
