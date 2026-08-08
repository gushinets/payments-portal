const fs = require("node:fs");
const path = require("node:path");

function readRuntimeEnv(repositoryRoot) {
  const runtimeEnvPath = path.join(repositoryRoot, ".harness/runtime.env");
  if (!fs.existsSync(runtimeEnvPath)) {
    return {};
  }

  const values = {};
  for (const rawLine of fs.readFileSync(runtimeEnvPath, "utf8").split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line || line.startsWith("#") || !line.includes("=")) {
      continue;
    }
    const [key, ...valueParts] = line.split("=");
    values[key.trim()] = valueParts.join("=").trim().replace(/^['"]|['"]$/g, "");
  }
  return values;
}

function loadRuntimeEnv(repositoryRoot, targetEnv = process.env) {
  const values = readRuntimeEnv(repositoryRoot);
  for (const [key, value] of Object.entries(values)) {
    if (targetEnv[key] === undefined || targetEnv[key] === "") {
      targetEnv[key] = value;
    }
  }
  return values;
}

module.exports = { loadRuntimeEnv, readRuntimeEnv };
