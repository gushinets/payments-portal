# ANY-741 Mako dependency maintenance

Status: implementation and evidence complete; human PR review remains.

## Scope and baseline

Base: `2e6d3adc63bd3d633709f6a5168fc14fb7141cdc` (fresh origin/main).
Python 3.12.10, uv 0.12.7; Alembic 1.18.5 requires unconstrained Mako,
currently locked at 1.4.1. No application Mako imports or TemplateLookup callers
were found. Alembic's `util.pyfiles.template_to_file` constructs a filename-based
Mako Template. The migration tree has no project `script.py.mako`.

This is package maintenance with ordinary behavior characterization. Local
vulnerability reproduction and crafted traversal inputs are excluded from scope.
Production uses Linux; package presence does not demonstrate reachable exposure.

## Steps

- [x] Inspect issue, dependencies, upstream release information and existing tests.
- [x] Characterize ordinary native Windows templates and disposable Alembic revision generation.
- [x] Use uv 0.12.7 to upgrade only Mako to 1.4.3 and inspect the lock diff.
- [x] Repeat focused tests; run API lock, fast and canonical checks and applicable PostgreSQL checks.
- [x] Build production API image, verify runtime/version, obtain fresh sanitized filesystem/image scans.
- [x] Review final diff/current main, publish focused PR and record remaining limitations.

## Release selection

[Upstream advisory](https://github.com/advisories/GHSA-5639-2j2p-m4mx)
identifies the Windows drive-letter URI issue and fix in 1.4.2.
[Changelog](https://docs.makotemplates.org/en/latest/changelog.html)
documents 1.4.3's correction to Windows test-suite execution, with native ntpath
coverage upstream. [PyPI 1.4.3](https://pypi.org/project/Mako/1.4.3/)
supports Python >=3.10. Choose this small patched release over the initial 1.4.2
fix; Alembic and MarkupSafe constraints remain compatible. Upstream evidence is
not an independent local verification of vulnerability-specific behavior.

### Immutable upstream provenance

Source inspected on 2026-11-17, using GitHub commit metadata/diffs and raw files
at the full commit IDs (not just the mutable changelog):

- Runtime fix: [000ed85e4e48771eff460bf4fc721fb43de80e08](https://github.com/sqlalchemy/mako/commit/000ed85e4e48771eff460bf4fc721fb43de80e08).
  In [Template URI validation](https://github.com/sqlalchemy/mako/blob/000ed85e4e48771eff460bf4fc721fb43de80e08/mako/template.py#L268-L280),
  normalization changes from host-dependent `os.path` to `posixpath`, matching
  lookup resolution. This is the runtime behavior correction associated with
  CVE-2026-102991 / GHSA-5639-2j2p-m4mx, shipped in 1.4.2.
- That commit adds/consolidates the
  [lookup regression matrix and in-root positive control](https://github.com/sqlalchemy/mako/blob/000ed85e4e48771eff460bf4fc721fb43de80e08/test/test_lookup.py#L136-L192)
  and [Template validation and accepted-URI matrices](https://github.com/sqlalchemy/mako/blob/000ed85e4e48771eff460bf4fc721fb43de80e08/test/test_template.py#L1469-L1530).
  Both exercise POSIX and Windows path semantics in upstream test source.
- Subsequent Windows test correction:
  [0d9f2d299816c8e3333828a32bbda7c90237761b](https://github.com/sqlalchemy/mako/commit/0d9f2d299816c8e3333828a32bbda7c90237761b),
  included between release tags `rel_1_4_2` and `rel_1_4_3`.
  [Corrected lookup parametrization](https://github.com/sqlalchemy/mako/blob/0d9f2d299816c8e3333828a32bbda7c90237761b/test/test_lookup.py#L136-L155)
  skips POSIX-emulation lookup rows on a Windows filesystem while retaining
  native `ntpath` rows there. Its diff touches only tests and a release note;
  it does not alter runtime code. This test-execution correction supports
  choosing 1.4.3 over the initial 1.4.2 patch.

These are inspected upstream sources, not upstream tests executed locally or a
claim that upstream CI results were independently verified. Local executions
cover ordinary compatibility only; they do not independently prove the
vulnerability-specific behavior. No local vulnerability reproduction was performed.

### Reproducible final production-image checks

Evidence follow-up on 2026-11-17 continues clean branch
`codex/any-741-patch-mako` at `52b131ce77bc9a6435bef96679f04ec94d3382cb`.
`git fetch origin` succeeded; fetched main remained
`2e6d3adc63bd3d633709f6a5168fc14fb7141cdc`. The image already exists;
no rebuild or dependency update is needed for this documentation-only change.

Shell: **PowerShell 7.6.9 on Windows**, from the checkout root. The following exact
block was executed successfully on 2026-11-17. It resolves and checks the local
image identity before running both disposable containers by that identity.

```powershell
$imageTag = 'payment-portal-api:any-741-mako'
$imageId = docker image inspect $imageTag --format '{{.Id}}'
if ($LASTEXITCODE -ne 0) { throw 'Production image is unavailable' }
if ($imageId -ne 'sha256:0d63ec140692c95515e0eee889a491082b5b98eac805624b183a1f2394597390') {
    throw 'Production image identity changed; inspect before reusing evidence'
}
docker image inspect $imageId --format '{{.Id}} user={{.Config.User}} repoDigests={{json .RepoDigests}}'
if ($LASTEXITCODE -ne 0) { throw 'Image inspection failed' }
docker run --rm --entrypoint python $imageId -c "from importlib.metadata import version; value = version('Mako'); assert value == '1.4.3', value; print('Mako=' + value)"
if ($LASTEXITCODE -ne 0) { throw 'Installed Mako version check failed' }
@'
import ast
import os
from pathlib import Path
from tempfile import TemporaryDirectory

from alembic import command
from alembic.config import Config

assert os.getuid() != 0, 'Expected normal non-root runtime user'
with TemporaryDirectory(prefix='any741-image-') as temporary:
    root = Path(temporary)
    config = Config(str(root / 'alembic.ini'))
    command.init(config, str(root / 'migrations'), template='generic')
    revision = command.revision(
        config, message='ordinary image compatibility', rev_id='741image'
    )
    assert revision is not None
    generated = Path(revision.path).read_text(encoding='utf-8')
    tree = ast.parse(generated)
    compile(tree, revision.path, 'exec')
    assert ast.get_docstring(tree).startswith('ordinary image compatibility')
    assert revision.revision == revision.module.revision == '741image'
    assert revision.down_revision is revision.module.down_revision is None
    assert revision.module.branch_labels is None
    assert revision.module.depends_on is None
    assert callable(revision.module.upgrade)
    assert callable(revision.module.downgrade)
    assert revision.module.upgrade() is None
    assert revision.module.downgrade() is None
    print('Alembic generic revision=741image down_revision=None: PASS')
    print('Generated Python, message, metadata, upgrade/downgrade: PASS')
print('Temporary environment removed; non-root execution: PASS')
'@ | docker run --rm -i --entrypoint python $imageId -
if ($LASTEXITCODE -ne 0) { throw 'Alembic production-image check failed' }
```

Both `docker run` commands exited **0**. Concise expected output, excluding
Alembic's temporary-path creation messages:

```text
Mako=1.4.3
Alembic generic revision=741image down_revision=None: PASS
Generated Python, message, metadata, upgrade/downgrade: PASS
Temporary environment removed; non-root execution: PASS
```

`docker image inspect` reports local `.Id`
`sha256:0d63ec140692c95515e0eee889a491082b5b98eac805624b183a1f2394597390`,
configured user `app`, and local RepoDigests entry
`payment-portal-api@sha256:0d63ec140692c95515e0eee889a491082b5b98eac805624b183a1f2394597390`.
This is a locally built production image and Docker's local content identity;
the local RepoDigests record does not establish publication to a registry.
No remote registry digest was verified in this follow-up. The separately built
historical CI image below has a different reported digest (`65bdafb3...`);
these executions do not reuse or reverify that CI image.

The commands preserve the image's default non-root user (no `--user` override),
override only the entrypoint, and use no mounts, database, application credentials
or repository migrations. Alembic uses its **installed generic template** inside
an automatically removed container-local temporary directory. Its generated
migration functions are empty, so checking/calling them requires no database.

Fresh follow-up checks: both image commands, documentation checks and PR diff
whitespace check passed. Broader API, PostgreSQL, frontend, runtime-liveness and
scanner checks below are earlier evidence attributed to their original revision;
they were not rerun for this evidence-only change because dependency, application,
test and image inputs are unchanged. Earlier local full-check limitations remain.
Historical automatic rechecks on `52b131ce77bc9a6435bef96679f04ec94d3382cb`
also finished successfully: [CI 44081695496](https://github.com/gushinets/payments-portal/actions/runs/44081695496)
and [security 44081695494](https://github.com/gushinets/payments-portal/actions/runs/44081695494).
Their statuses were read during this follow-up; they are not fresh local runs.

## Evidence

- Before update: lock check passed; four ordinary compatibility cases passed on
  native Windows with Mako 1.4.1. Initial restricted-process temporary-directory
  permission errors were resolved by running checks with an isolated test directory.
- After update: lock check, Ruff check/format and 62 focused dependency/template
  cases passed. Only the Mako package version/artifact entries changed in uv.lock;
  no manifest adjustment or other dependency update was needed.
- Nine existing Alembic/PostgreSQL compatibility checks passed against the
  worktree-isolated disposable PostgreSQL server. An initial attempt used incorrect
  default test credentials; the successful run used harness-generated credentials.
- Local production image `payment-portal-api:any-741-mako` built successfully;
  installed Mako is 1.4.3, ordinary Alembic generation inside Linux passed, and
  unchanged `security/trivy/verify-api-runtime.sh` passed (non-root and liveness).
- Local Docker `.Id`: `sha256:0d63ec140692c95515e0eee889a491082b5b98eac805624b183a1f2394597390`.
  Build inputs are baseline plus the targeted lock update; remaining source changes
  are tests and this evidence file and are not copied into the production target.
- PyPI JSON confirms Python >=3.10 and both 1.4.3 artifacts are non-yanked.
- Local `npm run test:api:fast`: 2265 passed, 43 skipped, one unrelated preflight
  queue-budget timing failure; that test passed when rerun alone. Subsequent
  `npm run check:fast` passed in full, including 2266 API tests and 43 skips.
  Full `npm run check` exited 1 at the unrelated Next.js `SecurityFatalError`
  notice during web build, after another 2266 API passes and 43 skips. Its later
  PostgreSQL/browser stages were not reached; isolated local PostgreSQL evidence
  and complete CI production/browser results cover those separately. No full
  local PASS is claimed; no frontend upgrade or suppression was made.
- Fresh local Trivy 0.72.0 API-filesystem and production-image vulnerability
  reports inventory Mako 1.4.3 and contain neither advisory ID. Sanitizer removed
  zero secret values. API-filesystem report SHA256:
  `22a8ccb89695a80f9010042e08eedc653a6acf4535b4ebf978f0aaddd0b057e2`;
  API-image report SHA256:
  `4e5d170e90c242959a7eaed8ff6c4ee7a8826287856150de8c4d9cbf9adb6458`.
  The broader local filesystem scan timed out in Dockerfile analysis; use the
  completed full CI filesystem scan below, not that incomplete local result.
- [Security CI 44079927528](https://github.com/gushinets/payments-portal/actions/runs/44079927528)
  passed on source `9272cb2e08ef90aff82d06fe005a0c8de82be150`.
  Downloaded sanitized artifact `14326258428` and verified its ZIP SHA256 against
  GitHub metadata: `bef5cf86f96a153249cdb10a32ca7d593cde1529710b3d449f1d4b21b7c8063f`.
  Full filesystem and final API-image reports contain Mako 1.4.3 and neither
  `CVE-2026-102991` nor `GHSA-5639-2j2p-m4mx`. CI image identity:
  `payment-portal-api@sha256:65bdafb3d45813d4e3021e673d621c1c5d37217849feda600b67df8153bf813d`.
  Existing runtime verification passed in CI too. Report absence concerns the
  target advisory only; it does not claim the repository has no other findings.
- CI code quality passed: fast/coverage API runs each 2308 passed, one skipped;
  frontend 454 passed, plus lint, typecheck and build.
- [CI 44079927567](https://github.com/gushinets/payments-portal/actions/runs/44079927567)
  passed completely on `9272cb2e`: production PostgreSQL workers total 1209 passed,
  one skipped; production images/API smoke passed; browser 248 passed, two skipped,
  React runtime four passed; Linux/Windows harness checks passed. Metadata passed.
  Evidence-only follow-up does not change tested application, lock or test sources.
- Independent read-only review found no actionable issues; final PR diff whitespace
  check passed. No peer or production/security policy change.
- No local vulnerability reproduction was performed. Ordinary Windows path tests
  do not independently prove the vulnerability-specific fix; that claim relies on
  the cited upstream fix and test evidence. No production exploit is demonstrated.

## Handoff

[ANY-741 - Patch Mako path traversal in API dependencies](https://github.com/gushinets/payments-portal/pull/178).
Final pre-submission fetch still resolves origin/main to `2e6d3adc`; no overlapping
changes to reconcile. Disposable local PostgreSQL was stopped using the canonical
worktree-local command; existing services and other worktrees were preserved.
Merge, deployment and issue completion require separate human instruction.
