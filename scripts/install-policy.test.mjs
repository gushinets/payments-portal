import assert from 'node:assert/strict';
import { execFile, spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { createServer } from 'node:http';
import { promisify } from 'node:util';
import { copyFileSync, existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('../', import.meta.url));
const read = (file) => readFileSync(join(root, file), 'utf8');

test('locked npm install skips hooks and reports pending explicit and implicit hooks', async (t) => {
  const project = mkdtempSync(join(tmpdir(), 'portal-install-policy-'));
  t.after(() => rmSync(project, { recursive: true, force: true, maxRetries: 3 }));
  const npm = process.env.npm_execpath;
  assert.ok(npm, 'Run via npm run test:install-policy');
  const userconfig = join(project, 'user.npmrc');
  writeFileSync(userconfig, '');
  const marker = join(project, 'ran.txt');
  const env = Object.fromEntries(
    Object.entries(process.env).filter(([name]) => !/^npm_config_/i.test(name)),
  );
  const npmRun = (cwd, ...args) => {
    const result = spawnSync(process.execPath, [
      npm, '--offline', '--no-audit', '--no-fund',
      '--userconfig', userconfig, '--cache', join(project, 'cache'), ...args,
    ], { cwd, env, encoding: 'utf8', timeout: 30_000 });
    assert.ifError(result.error);
    return { status: result.status, output: result.stdout + result.stderr };
  };
  const passed = ({ status, output }) => assert.equal(status, 0, output);
  const writeManifest = (dir, data) => writeFileSync(join(dir, 'package.json'), JSON.stringify(data));

  const packages = new Map();
  const pack = (name, { implicit = false, os } = {}) => {
    const dir = join(project, name);
    mkdirSync(dir);
    const manifest = { name, version: '1.0.0', os, scripts: implicit ? {} : { postinstall: 'node mark.cjs' } };
    writeManifest(dir, manifest);
    if (implicit) writeFileSync(join(dir, 'binding.gyp'), '{}');
    writeFileSync(join(dir, 'mark.cjs'),
      `require('node:fs').appendFileSync(${JSON.stringify(marker)}, '${name}\\n')`);
    passed(npmRun(dir, 'pack', '--ignore-scripts', '--pack-destination', project));
    const archive = readFileSync(join(project, `${name}-1.0.0.tgz`));
    const integrity = 'sha512-' + createHash('sha512').update(archive).digest('base64');
    packages.set(name, { manifest, archive, integrity });
  };

  const workspace = join(project, 'workspace');
  mkdirSync(workspace);
  pack('explicit');
  const implicitPackages = ['implicit-dev', 'implicit-optional', 'implicit-peer'];
  for (const name of implicitPackages) pack(name, { implicit: true });
  pack('inapplicable', { os: [process.platform === 'win32' ? 'linux' : 'win32'] });
  const server = createServer((request, response) => {
    const [, name, segment] = request.url.split('/');
    const pkg = packages.get(name);
    if (!pkg) {
      response.writeHead(404).end();
    } else if (segment === '-') {
      response.end(pkg.archive);
    } else {
      response.setHeader('content-type', 'application/json');
      response.end(JSON.stringify({
        name,
        versions: {
          '1.0.0': {
            ...pkg.manifest,
            dist: { tarball: `${registry}${name}/-/${name}-1.0.0.tgz`, integrity: pkg.integrity },
          },
        },
      }));
    }
  });
  await new Promise((listen) => server.listen(0, '127.0.0.1', listen));
  t.after(() => server.close());
  const registry = `http://127.0.0.1:${server.address().port}/`;
  const fixtureNpm = async (cwd, ...args) => {
    try {
      const result = await promisify(execFile)(process.execPath, [
        npm, '--no-audit', '--no-fund', '--registry', registry,
        '--userconfig', userconfig, '--cache', join(project, 'cache'), ...args,
      ], { cwd, env: { ...env, NO_PROXY: '127.0.0.1' }, timeout: 30_000 });
      return { status: 0, output: result.stdout + result.stderr };
    } catch (error) {
      assert.equal(typeof error.code, 'number', String(error));
      return { status: error.code, output: error.stdout + error.stderr };
    }
  };
  const installScript = join(root, 'scripts/install-npm-dependencies.mjs');
  const manifest = {
    name: 'portal-policy-fixture', private: true, workspaces: ['workspace'],
    optionalDependencies: { inapplicable: '1.0.0' },
    allowScripts: { 'inapplicable@1.0.0': false },
    scripts: { 'deps:install': `node "${installScript}"` },
  };
  const workspaceManifest = {
    name: 'policy-workspace', version: '1.0.0',
    dependencies: { explicit: '1.0.0' },
    devDependencies: { 'implicit-dev': '1.0.0' },
    optionalDependencies: { 'implicit-optional': '1.0.0' },
    peerDependencies: { 'implicit-peer': '1.0.0' },
    scripts: { proof: 'node -e "console.log(123)"' },
  };
  writeManifest(project, manifest);
  writeManifest(workspace, workspaceManifest);
  copyFileSync(join(root, '.npmrc'), join(project, '.npmrc'));
  passed(await fixtureNpm(project, 'install', '--package-lock-only', '--ignore-scripts'));

  env.npm_config_dangerously_allow_all_scripts = 'true';
  const pendingBindings = implicitPackages.map((name) => ({
    name, path: join(project, 'node_modules', name, 'binding.gyp'),
  }));
  const installSettings = [
    ['npm_config_dry_run', 'true'],
    ['npm_config_package_lock_only', 'true'],
    ['npm_config_workspaces', 'false'],
    ['npm_config_omit', 'dev'],
    ['npm_config_omit', 'optional'],
    ['npm_config_omit', 'peer'],
  ];
  for (const [setting, value] of installSettings) {
    for (const { path } of pendingBindings) rmSync(path, { force: true });
    env[setting] = value;
    const pending = await fixtureNpm(project, 'run', 'deps:install');
    delete env[setting];
    assert.equal(existsSync(marker), false, pending.output);
    assert.notEqual(pending.status, 0, pending.output);
    assert.match(pending.output, /Review dependency install hooks/);
    assert.match(pending.output, /explicit@1\.0\.0/);
    for (const { name, path } of pendingBindings) {
      assert.ok(pending.output.includes(`${name}@1.0.0`), pending.output);
      assert.ok(existsSync(path), pending.output);
    }
    assert.doesNotMatch(pending.output, /inapplicable@1\.0\.0/);
    assert.equal(existsSync(join(project, 'node_modules/inapplicable')), false);
  }
  delete env.npm_config_dangerously_allow_all_scripts;

  for (const name of ['explicit', ...implicitPackages]) {
    manifest.allowScripts[`${name}@1.0.0`] = false;
  }
  writeManifest(project, manifest);
  passed(await fixtureNpm(project, 'run', 'deps:install'));
  passed(await fixtureNpm(workspace, 'ci'));
  assert.equal(existsSync(marker), false);
  passed(await fixtureNpm(workspace, 'run', 'proof'));

  // Prove an exact approval works on the already unpacked harmless fixture.
  // The Portal install pipeline has no approved packages and runs no rebuild.
  manifest.allowScripts['explicit@1.0.0'] = true;
  writeManifest(project, manifest);
  passed(await fixtureNpm(project, 'rebuild', 'explicit', '--ignore-scripts=false'));
  assert.equal(readFileSync(marker, 'utf8'), 'explicit\n');
});

test('CI, Docker and the local harness use the locked install policy', () => {
  const ci = read('.github/workflows/ci.yml');
  const apiDocker = read('apps/api/Dockerfile');
  const webDocker = read('apps/web/Dockerfile');
  const harness = read('scripts/repo.py');
  const ciSyncs = [...ci.matchAll(/run: uv sync([^\r\n]*)/g)];
  const dockerSyncs = [...apiDocker.matchAll(/RUN uv sync([^\r\n]*)/g)];
  assert.equal(ciSyncs.length, 3);
  assert.equal(dockerSyncs.length, 2);
  for (const [, options] of [...ciSyncs, ...dockerSyncs]) {
    assert.match(options, /\B--locked\b.*\B--no-build\b/);
  }
  assert.equal([...ci.matchAll(/run: npm run deps:install/g)].length, 3);
  assert.doesNotMatch(ci, /\brun: (?:npm ci|npx playwright)\b/);
  assert.match(webDocker, /COPY \.npmrc package.json package-lock.json/);
  assert.match(webDocker, /COPY scripts\/install-npm-dependencies\.mjs[^\r\n]*\r?\n\s*RUN .*npm run deps:install/);
  assert.match(harness, /api_uv_command\("sync", "--locked", "--dev", "--no-build"\)/);
  assert.match(harness, /run\(\[npm, "run", "deps:install"\]\)/);
  const manifest = JSON.parse(read('package.json'));
  assert.match(manifest.scripts['playwright:install'], /^node node_modules\//);
  assert.match(read('.npmrc'), /^ignore-scripts=true\r?$/m);
});
