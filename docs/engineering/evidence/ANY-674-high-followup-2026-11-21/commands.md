# Reproduction and evidence scope

Run from the repository root. Keep caches/archives on D: under private .harness.
Do not publish raw runtime environment inspection output. Historical archives
are retained, not recreated from moving repositories to imitate old contents.

```powershell
git fetch origin
git rev-parse origin/main HEAD
docker build --pull --no-cache --platform linux/amd64 --target production -f apps/api/Dockerfile -t payment-portal-api:any674-high-after-20261121 .
docker image inspect --format '{{.Id}} {{.Os}}/{{.Architecture}} {{.Config.User}}' payment-portal-api:any674-high-after-20261121
docker save -o .harness/any-674-high-followup/after-image.tar payment-portal-api:any674-high-after-20261121
```

Fresh-before source d1ff9c34e8c8957661479e669c29187bc35a6f8a used its own context,
same build flags, tag payment-portal-api:any674-high-before-d1ff. Selected final
runtime source e5df91f4f6545f63b3cc371fe7d717f8025af3da; ba32f4d0 changes tests only.
Python3.12.16 slim Trixie base digest:
`sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b`.
No-cache plus fresh indexes resolves supported updates; future rebuilds can obtain
newer package versions and must capture their actual inventories separately.

Scan archives sequentially with the same frozen database, downloaded once before
the comparison. All three scans used this shape, changing only input/output name:

```sh
docker run --rm --network none \
  --mount type=bind,src=<absolute-evidence-dir>,dst=/evidence \
  --mount type=bind,src=<absolute-repository-root>,dst=/src,readonly \
  aquasec/trivy@sha256:cffe3f5161a47a6823fbd23d985795b3ed72a4c806da4c4df16266c02accdd6f \
  image --input /evidence/after-image.tar --cache-dir /evidence/trivy-cache \
  --skip-db-update --skip-java-db-update --offline-scan \
  --config /src/trivy.yaml --ignorefile /src/.trivyignore.yaml \
  --scanners vuln,secret --format json --output /evidence/reports/after-image.json \
  --timeout 15m --quiet
python scripts/repo.py trivy redact <report-directory>
bash security/trivy/verify-api-runtime.sh payment-portal-api:any674-high-after-20261121
bash security/trivy/verify-api-postgres.sh payment-portal-api:any674-high-after-20261121
```

Windows Git Bash needs MSYS_NO_PATHCONV=1 and repository venv available as python3.
Baseline offline verifier was extracted from d1ff9c34. Baseline PostgreSQL helper
preserves no-new-privileges but omits new cap-drop/bounding-zero assertion; final
uses checked-in scripts. Helpers create/remove only their disposable resources.
Read-only inspect-api-components.py and inspect-api-isolation.py run mounted from
security/trivy against actual images. Final isolation profile is
`--cap-drop ALL --security-opt no-new-privileges:true --network none`;
baseline retains no-new-privileges and the default capability bounding set.

```powershell
.venv/Scripts/python.exe -m pytest apps/api/tests/test_production_cve_boundaries.py -q
npm run check:fast
npm run check
```

At ba32f4d0 local canonical exit codes1/1 reflect Node host-memory exhaustion;
downstream unreached stages are not passing. Hosted CI44915352941 and
Security44915353123 succeeded on that revision. Earlier e5df91f4 CI failures
were invalid production SQLite test fixtures, corrected in ba32f4d0.
