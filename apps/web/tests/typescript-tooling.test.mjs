import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import test from "node:test";
import { fileURLToPath } from "node:url";

const repositoryRoot = fileURLToPath(new URL("../../..", import.meta.url));
const npmExecutable = process.platform === "win32" ? "npm.cmd" : "npm";

function runWebTypecheck(...extraArguments) {
  return execFileSync(
    npmExecutable,
    [
      "--workspace",
      "@anytoolai/web",
      "run",
      "typecheck",
      "--",
      ...extraArguments
    ],
    {
      cwd: repositoryRoot,
      encoding: "utf8",
      shell: process.platform === "win32"
    }
  );
}

test("the web typecheck script runs TypeScript 7", () => {
  const version = runWebTypecheck("--version");

  assert.match(version, /Types generated successfully/);
  assert.match(version, /\nVersion 7\./);
});

test("the web TypeScript project checks the root Playwright configs", () => {
  const checkedFiles = runWebTypecheck("--listFilesOnly").replaceAll("\\", "/");

  assert.match(checkedFiles, /\/playwright\.config\.ts$/m);
  assert.match(checkedFiles, /\/playwright\.react-runtime\.config\.ts$/m);
});

test("the complete web TypeScript project typechecks without errors", () => {
  assert.doesNotThrow(() => runWebTypecheck());
});
