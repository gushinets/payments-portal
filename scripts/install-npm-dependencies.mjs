import { spawnSync } from 'node:child_process';
import { readFileSync } from 'node:fs';

const cli = process.env.npm_execpath;
if (!cli) {
  throw new Error('Run this command with npm run deps:install.');
}

function npm(args, capture = false) {
  const result = spawnSync(process.execPath, [cli, ...args], {
    encoding: 'utf8',
    stdio: capture ? ['ignore', 'pipe', 'inherit'] : 'inherit',
  });
  if (result.error) throw result.error;
  if (result.status !== 0) process.exit(result.status ?? 1);
  return result.stdout;
}

// Review the unpacked root and workspace dependencies, including the
// selected platform's optional packages and development and peer dependencies.
npm([
  'ci', '--ignore-scripts', '--dry-run=false', '--package-lock-only=false',
  '--workspaces', '--include-workspace-root',
  '--include=dev', '--include=optional', '--include=peer',
]);

// Check all marked lock entries, including optional packages for other platforms.
// npm also examines the actual tree below for implicit hooks missing from the lock.
const { allowScripts } = JSON.parse(readFileSync('package.json', 'utf8'));
const { packages } = JSON.parse(readFileSync('package-lock.json', 'utf8'));
const pending = new Set();
for (const [location, entry] of Object.entries(packages)) {
  if (!entry.hasInstallScript) continue;
  const name = entry.name ?? location.split('node_modules/').at(-1);
  const key = `${name}@${entry.version}`;
  if (!Object.hasOwn(allowScripts, key)) pending.add(key);
}

const installed = JSON.parse(npm([
  'install-scripts', 'ls', '--json', '--dangerously-allow-all-scripts=false',
], true));
for (const { changes } of installed.allowScripts) {
  for (const { key } of changes) pending.add(key);
}
if (pending.size > 0) {
  console.error('Review dependency install hooks before continuing:');
  const sortedKeys = [...pending].sort((left, right) => {
    if (left < right) return -1;
    if (left > right) return 1;
    return 0;
  });
  for (const key of sortedKeys) console.error(`  ${key}`);
  console.error('See docs/engineering/dependency-installation.md for the review procedure.');
  process.exitCode = 1;
}
