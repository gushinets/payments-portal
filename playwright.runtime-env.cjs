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
  if (targetEnv.PLAYWRIGHT_DATABASE_URL === undefined || targetEnv.PLAYWRIGHT_DATABASE_URL === "") {
    const databaseUrl = hostDatabaseUrlFromRuntimeEnv(targetEnv);
    if (databaseUrl !== null) {
      targetEnv.PLAYWRIGHT_DATABASE_URL = databaseUrl;
    }
  }
  return values;
}

function hostDatabaseUrlFromRuntimeEnv(targetEnv) {
  const requiredKeys = [
    "POSTGRES_DB",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "POSTGRES_PORT"
  ];
  if (requiredKeys.some((key) => targetEnv[key] === undefined || targetEnv[key] === "")) {
    return null;
  }

  const user = encodeURIComponent(targetEnv.POSTGRES_USER);
  const password = encodeURIComponent(targetEnv.POSTGRES_PASSWORD);
  const database = encodeURIComponent(targetEnv.POSTGRES_DB);
  return `postgresql+psycopg://${user}:${password}@127.0.0.1:${targetEnv.POSTGRES_PORT}/${database}`;
}

module.exports = { loadRuntimeEnv, readRuntimeEnv };
