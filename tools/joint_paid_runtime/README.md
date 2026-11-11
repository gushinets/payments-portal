# Local paid-runtime acceptance

This Step 16 harness runs the real Portal API/embedded worker and Kernel API/worker
over TCP with two independent PostgreSQL 18.4 Compose projects. It uses each
repository's prepared Python environment and existing app composition. Nothing is
installed, built into an image, pulled, published or deployed by the harness.

From the Portal root:

```bash
./.venv/bin/python -m pytest -q tools/joint_paid_runtime/tests
./.venv/bin/python tools/joint_paid_runtime/runtime.py --browser
```

The second command supplies both origins and private identity-fixture input to
`npm run test:e2e:joint`, using the existing desktop/mobile projects and the
dedicated `playwright.joint.config.ts`. Joint HTTP acceptance lives outside the
ordinary API discovery roots; the ordinary browser configuration excludes
`apps/web/e2e/joint`. These suites require an explicit invocation and never run
in the single-repository CI jobs. Do not run another Next
build/dev process against the same checkouts concurrently. `ANY766_KERNEL_ROOT`
optionally selects the prepared peer checkout (default: the neighboring clone).

External substitutions are explicit: LBX uses the existing purchase recordings
served on loopback, AI uses Kernel's deterministic provider fixtures, and the
second backend is a synthetic protocol demonstrator. Temporary product copies
enable only the four selected production declarations; committed defaults retain
disabled sales. Purchased quantities are isolated test values. Purchases and
access are established through publication, consent, preparation and the normal
reconciliation writer, followed by real session/service authentication. This
proves neither a live payment nor real Document Summary adoption.

Each invocation owns fresh, unpredictable Compose project names and named volumes.
Cleanup removes only those resources, including after partial startup failure;
it never resets an existing database or runs global Docker cleanup. Private logs
and fixture credentials remain in the printed mode-0700 `/tmp/any766-joint-*`
directory. Do not share the identity file. The HTTP case recreates its own database
containers and verifies retained purchases, usage and revision floors.

Optional container-to-container transport uses Portal's `docker-compose.peer.yml`
and Kernel's `infra/compose/docker-compose.peer.yml`. Set an explicitly created
`PAID_RUNTIME_PEER_NETWORK`, directional credentials and peer origins; only app
services join it. Databases stay private. These overlays are local topology inputs,
not installation/release tooling (Step 17).

Kernel dev now uses `postgres18-data:/var/lib/postgresql`, matching its existing
production volume convention and the PostgreSQL 18 image layout. Existing named
volumes retain their identity. An older dev container may have an anonymous volume:
inspect and back it up before recreating that existing project, then explicitly
reattach the retained volume through an operator-owned override. Merely adding the
new named mount does not transfer old data. The harness never performs that
conversion or touches those existing projects.

The 2026-11-11 acceptance scope prioritizes common backend auth/access, consumer
isolation, owner-directed usage/exhaustion and the main paid journey. Broad suites
and the remaining full failure/concurrency matrix are deferred at the user's
request; focused acceptance is not a claim that those gates passed.
