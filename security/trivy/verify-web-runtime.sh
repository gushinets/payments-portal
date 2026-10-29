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

docker run --rm --network none --entrypoint sh "$image_ref" -ec '
  test "$(id -u)" -ne 0
  test "$(node --version)" = "v24.22.1"

  # APK compares these constraints against the installed package database.
  for package_constraint in \
    "libcrypto3>=3.5.8-r0" \
    "libssl3>=3.5.8-r0" \
    "musl>=1.2.6-r3" \
    "musl-utils>=1.2.6-r3" \
    "zlib>=1.3.2-r1"
  do
    if ! apk info --exists --verbose "$package_constraint"; then
      echo "Missing or vulnerable runtime package: $package_constraint" >&2
      exit 1
    fi
  done

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

docker run --rm -i --network none --entrypoint node "$image_ref" <<'NODE'
const assert = require('node:assert/strict');
const { createRequire } = require('node:module');
const { deflateSync, gunzipSync, gzipSync, inflateSync } = require('node:zlib');
const sharp = createRequire('/app/apps/web/server.js')('sharp');

const compressionInput = Buffer.concat([
  Buffer.from('AnyToolAI runtime compression: '.repeat(64)),
  Buffer.from([0, 1, 127, 128, 255])
]);
assert.deepEqual(gunzipSync(gzipSync(compressionInput)), compressionInput);
assert.deepEqual(inflateSync(deflateSync(compressionInput)), compressionInput);
console.log('PASS: gzip/deflate round trips', process.versions.zlib);

async function verifyImageProcessing() {
  assert.ok(Object.keys(require.cache).some(path =>
    path.includes('/@img/sharp-') && path.endsWith('.node')
  ), 'expected a loaded native sharp addon');

  const png = await sharp({ create: {
    width: 128, height: 64, channels: 3,
    background: { r: 30, g: 100, b: 180 }
  }}).png().toBuffer();
  const webp = await sharp(png).resize(64, 32).webp().toBuffer();
  const { info, data } = await sharp(webp).raw().toBuffer({ resolveWithObject: true });
  assert.equal(info.width, 64);
  assert.equal(info.height, 32);
  assert.ok(data.length > 0);
  console.log('PASS: native sharp PNG/WebP processing', JSON.stringify(sharp.versions));
}

verifyImageProcessing().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
NODE
