# Dependency installation policy

Use Node.js **24.22.1** with its bundled **npm 11.19.1**, CPython **3.12**
and **uv 0.12.7**. Run `npm run repo:doctor` to check the local tools and
`npm run repo:setup` to install dependencies and the locked Playwright
Chromium revision. Use `npm run deps:install` to repeat just the JavaScript
install and `npm run sync:api` to repeat just the API sync.
[Node release and bundled npm](https://nodejs.org/en/download/archive/v24.22.1)

## npm

The root workspace policy applies to CI, the web dependency image layer and
the local harness. `npm run deps:install` runs `npm ci --ignore-scripts` with
the checked-in lock. The root `.npmrc` also defaults direct npm install and
rebuild commands to script-free mode. The installer checks both the lock and
npm's installed-tree report. Any pending hook stops setup and identifies the
package to review. The lock check includes marked packages for inactive
platforms. The installed-tree check includes implicit `node-gyp rebuild`
hooks whose presence can only be determined after unpacking.

The npm 11.19.1 strict preflight detects declared hooks recorded in the lock,
but a clean install has no on-disk `binding.gyp` for the preflight to inspect.
A fixture with no explicit install script reached `node-gyp rebuild` without
the script-free policy. Detection therefore takes place after a script-free
install. The project currently approves zero dependency lifecycle hooks.
[Versioned npm install documentation](https://docs.npmjs.com/cli/v11/commands/npm-ci/)
and [npm 11.19.1 hook detection source](https://github.com/npm/cli/blob/v11.19.1/workspaces/arborist/lib/install-scripts.js)

Commands explicitly invoked with `npm run` still run. Playwright aliases use
the installed `@playwright/test` entrypoint and fail if it is missing. The
explicit browser install downloads Chromium from the Playwright distribution
service. The CI-only `--with-deps` option also installs OS packages on the
runner.

## Audited npm decisions

The initial inventory used the `package-lock.json` from `49ed895d`. It
verified integrity and inspected the top-level manifest and `binding.gyp`
presence in 804 distinct public registry archives across 847 lock paths,
including platform-specific optional packages and nested copies. Five archives
contained active lifecycle hooks. Two further entries had historical install
markers in the lock with no lifecycle hook or `binding.gyp` in the published
archive. `sharp`, used by Next, has no active hook in its resolved archive.
Matching platform binaries remain normal locked optional dependencies.

| Resolved package and owning path | Hook, effects and decision |
| --- | --- |
| `@parcel/watcher@2.6.0`, web → next-intl | **Deny.** `install` runs `scripts/build-from-source.js`. With `npm_config_build_from_source=true` it invokes `node-gyp rebuild` via the shell, which can fetch Node headers and writes compiled artifacts under `build/`. The script otherwise does nothing. Published watcher binaries cover supported Linux glibc/musl and Windows architectures. [Upstream install script](https://github.com/parcel-bundler/watcher/blob/v2.6.0/scripts/build-from-source.js) |
| `@swc/core@1.16.2`, web → next-intl | **Deny.** `postinstall.js` loads native bindings to validate them. On failure it can run `npm install @swc/wasm@1.16.2` against the configured npm registry from a temporary directory, move the resulting package into the project `node_modules`, and remove the temporary files. The native optional packages used on Windows and Linux cover the supported targets. [Upstream SWC package](https://github.com/swc-project/swc/tree/main/packages/core) |
| `esbuild@0.28.2`, web → Vite | **Deny.** `install.js` validates the platform binary by invoking `--version`, can hard-link it over the wrapper on Unix, and can rewrite the wrapper and library for a manual override. If the binary is missing it tries a nested npm install and then the public npm registry directly, checking the package's per-binary SHA-256 before writing the binary. The normal JS API and CLI resolve the locked platform package on Linux and Windows. [Upstream install source](https://github.com/evanw/esbuild/blob/v0.28.2/lib/npm/node-install.ts) |
| `msw@2.15.0`, direct web dev dependency and Vitest mocker optional peer | **Deny.** `config/scripts/postinstall.js` reads the install root's manifest. If `msw.workerDirectory` is set, it launches the bundled CLI to copy `mockServiceWorker.js` to those directories. No network is needed for the copy. Portal component tests use `msw/node` and no worker directory is configured. Applies to Linux and Windows. [Upstream hook](https://github.com/mswjs/msw/blob/v2.15.0/config/scripts/postinstall.js) |
| `unrs-resolver@1.12.2`, web → eslint-config-next → eslint-import-resolver-typescript | **Deny.** `postinstall.js` calls locked `napi-postinstall@0.3.4`. It locates the selected native binary, with `ldd --version` available for Linux detection. Missing bindings can trigger another npm install and a direct registry download, writing or moving binding files under `node_modules` and cleaning temporary files. The locked Windows and glibc/musl bindings suffice for lint. [Upstream resolver](https://github.com/unrs/unrs-resolver) and [helper source](https://github.com/un-ts/napi-postinstall) |
| `fsevents@2.3.2` (top level), web → Playwright | **Deny.** Registry archive ships `fsevents.node`; it has no install entrypoint or implicit native build despite the lock marker. Release-time `prepublishOnly` invokes the upstream native build and is outside a registry install. macOS only. [Upstream release manifest](https://github.com/fsevents/fsevents/blob/v2.3.2/package.json) |
| `fsevents@2.3.3` (under Vite), web → Vite and Vite → Rollup | **Deny.** The separate resolved archive likewise ships the native binary and has no install entrypoint or implicit build. macOS only. [Upstream release manifest](https://github.com/fsevents/fsevents/blob/v2.3.3/package.json) |

When a dependency update changes a reviewed package's resolved version,
integrity, hook or invoked helper, review the exact new archives before
recording a decision. Include the owning path, platform, entrypoints,
subprocesses, writes and network destinations in the update PR. Run the
installer on supported platforms and use `npm install-scripts ls` after
unpacking to inspect pending hooks. Generate lock changes with the declared
npm version. Keep lifecycle scripts disabled while generating the lock.

If a future dependency genuinely requires execution, document the exact
package, version, entrypoint, affected platform and why the prebuilt
distribution is insufficient. Add and prove the narrow execution path on
supported platforms as part of that change. Existing decisions apply only to
the reviewed resolutions.

## Python

CI, the API Docker dependency stages and `npm run sync:api` use
`uv sync --locked --no-build`. Keep the requested group flags and
`--no-install-project` in the image. The API declares `package = false`, so
the local project is not built by the canonical sync. uv can reuse wheels
already in its cache. For wheel availability evidence, run against an empty
cache and environment. The control applies to source-distribution builds
during these installs. First-party build and editable workflows have their own
execution paths. The README also uses pip's wheel-only option to bootstrap uv.

If a platform lacks a wheel, identify the package, version and platform.
Keep the wheel-only default and resolve availability or review a narrowly
scoped exception. There are no exceptions in this policy.
[uv command reference](https://docs.astral.sh/uv/reference/cli/#uv-sync--no-build)
