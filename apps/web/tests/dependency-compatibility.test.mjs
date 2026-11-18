import assert from "node:assert/strict";
import { mkdtemp, mkdir, rm, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { dirname, join, resolve } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const repositoryRoot = fileURLToPath(new URL("../../..", import.meta.url));

test("Sentry artifact globbing preserves ordinary chunk selection and literal paths", async () => {
  // Exercise the actual Sentry consumer, including its absolute/nodir defaults.
  // This internal seam is intentionally coupled to the pinned Sentry release.
  const bundlerRoot = dirname(require.resolve("@sentry/bundler-plugins/package.json"));
  const { globFiles } = require(join(bundlerRoot, "build/cjs/core/glob.js"));
  const { escape } = createRequire(join(bundlerRoot, "package.json"))("glob");
  const temporaryRoot = join(repositoryRoot, ".harness", "tmp");
  await mkdir(temporaryRoot, { recursive: true });
  const fixture = await mkdtemp(join(temporaryRoot, "sentry-glob-"));
  try {
    await mkdir(join(fixture, "chunks", "nested"), { recursive: true });
    await mkdir(join(fixture, "chunks", "directory.js"));
    for (const name of ["entry.js", "entry.js.map", "ignored.js", "literal[1].js", "nested/module.mjs", "nested/module.cjs", "nested/style.css"]) {
      await writeFile(join(fixture, "chunks", name), "fixture");
    }
    const selected = await globFiles("chunks/**/*.{js,mjs,cjs}", {
      cwd: fixture,
      ignore: ["**/ignored.js"]
    });
    assert.deepEqual(selected.map(path => resolve(path)).sort(), [
      "entry.js", "literal[1].js", "nested/module.mjs", "nested/module.cjs"
    ].map(path => resolve(fixture, "chunks", path)).sort());
    const literal = join(fixture, "chunks", "literal[1].js");
    assert.deepEqual((await globFiles(escape(literal.replaceAll("\\", "/")))).map(path => resolve(path)), [resolve(literal)]);
  } finally {
    await rm(fixture, { recursive: true, force: true });
  }
});

test("the real Sentry Next SDK retains the Portal's reporting and initialization APIs", async () => {
  const sentry = require("@sentry/nextjs");
  for (const name of ["init", "captureException", "captureRequestError"]) {
    assert.equal(typeof sentry[name], "function", name);
  }
  // No network transport or default integrations: ordinary offline SDK smoke.
  const client = sentry.init({
    enabled: false,
    defaultIntegrations: false,
    tracesSampleRate: 0,
    dataCollection: { userInfo: false, cookies: false, httpHeaders: false, httpBodies: [], urlQueryParams: false }
  });
  try {
    assert.equal(client.getOptions().enabled, false);
    assert.equal(client.getOptions().dataCollection.userInfo, false);
    assert.equal(typeof sentry.captureException(new Error("Compatibility fixture")), "string");
  } finally {
    await sentry.close(1000);
  }
});
