import assert from "node:assert/strict";
import { mkdir, mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import test from "node:test";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { loadRuntimeEnv } = require("../../../playwright.runtime-env.cjs");

test("Playwright runtime env loader shares the harness signing secret", async () => {
  const repositoryRoot = await mkdtemp(`${tmpdir()}/payments-playwright-env-`);
  await mkdir(`${repositoryRoot}/.harness`);
  await writeFile(
    `${repositoryRoot}/.harness/runtime.env`,
    [
      "CLOUDPAYMENTS_API_SECRET=secret_from_runtime",
      "PLAYWRIGHT_API_BASE_URL=http://127.0.0.1:8123",
      ""
    ].join("\n"),
    "utf8"
  );

  const targetEnv = {};
  loadRuntimeEnv(repositoryRoot, targetEnv);

  assert.equal(targetEnv.CLOUDPAYMENTS_API_SECRET, "secret_from_runtime");
  assert.equal(targetEnv.PLAYWRIGHT_API_BASE_URL, "http://127.0.0.1:8123");
});

test("Playwright runtime env loader preserves explicit process overrides", async () => {
  const repositoryRoot = await mkdtemp(`${tmpdir()}/payments-playwright-env-`);
  await mkdir(`${repositoryRoot}/.harness`);
  await writeFile(
    `${repositoryRoot}/.harness/runtime.env`,
    "CLOUDPAYMENTS_API_SECRET=secret_from_runtime\n",
    "utf8"
  );

  const targetEnv = { CLOUDPAYMENTS_API_SECRET: "secret_from_process" };
  loadRuntimeEnv(repositoryRoot, targetEnv);

  assert.equal(targetEnv.CLOUDPAYMENTS_API_SECRET, "secret_from_process");
});

test("Playwright runtime env loader exposes a host database URL", async () => {
  const repositoryRoot = await mkdtemp(`${tmpdir()}/payments-playwright-env-`);
  await mkdir(`${repositoryRoot}/.harness`);
  await writeFile(
    `${repositoryRoot}/.harness/runtime.env`,
    [
      "DATABASE_URL=postgresql+psycopg://anytoolai:anytoolai-local-only@postgres:5432/payments_test",
      "POSTGRES_DB=payments_test",
      "POSTGRES_USER=anytoolai",
      "POSTGRES_PASSWORD=anytoolai-local-only",
      "POSTGRES_PORT=32053",
      ""
    ].join("\n"),
    "utf8"
  );

  const targetEnv = {};
  loadRuntimeEnv(repositoryRoot, targetEnv);

  assert.equal(
    targetEnv.PLAYWRIGHT_DATABASE_URL,
    "postgresql+psycopg://anytoolai:anytoolai-local-only@127.0.0.1:32053/payments_test"
  );
  assert.equal(
    targetEnv.DATABASE_URL,
    "postgresql+psycopg://anytoolai:anytoolai-local-only@postgres:5432/payments_test"
  );
});

test("Playwright runtime env loader preserves explicit database URL override", async () => {
  const repositoryRoot = await mkdtemp(`${tmpdir()}/payments-playwright-env-`);
  await mkdir(`${repositoryRoot}/.harness`);
  await writeFile(
    `${repositoryRoot}/.harness/runtime.env`,
    [
      "POSTGRES_DB=payments_test",
      "POSTGRES_USER=anytoolai",
      "POSTGRES_PASSWORD=anytoolai-local-only",
      "POSTGRES_PORT=32053",
      ""
    ].join("\n"),
    "utf8"
  );

  const targetEnv = {
    PLAYWRIGHT_DATABASE_URL: "sqlite+pysqlite:///:memory:"
  };
  loadRuntimeEnv(repositoryRoot, targetEnv);

  assert.equal(targetEnv.PLAYWRIGHT_DATABASE_URL, "sqlite+pysqlite:///:memory:");
});
