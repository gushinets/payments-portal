"""Step 16: real apps/auth/HTTP/PG; only external LBX/AI are deterministic.

Requires Docker and the prepared paired checkout. Missing prerequisites fail;
no endpoint mocks, dependency overrides or trusted-principal substitutions.
Run explicitly with pytest tools/joint_paid_runtime/tests; this suite is outside
the ordinary API test discovery roots.
"""

import base64
import hashlib
import json
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from calendar import monthrange
from datetime import UTC, datetime
from time import monotonic, sleep
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import create_engine, text

from tools.joint_paid_runtime.runtime import JointRuntime, KERNEL, PORTAL

pytestmark = pytest.mark.postgres
BRIEF = "Need a website for my bakery by the holidays, modern but traditional."
CASES = (
    (
        "proposal_ai",
        "proposal_ai.generate_v1",
        {
            "task_text": "Build a 5-page marketing site for a local bakery within two weeks.",
            "freelancer_positioning": "Freelance web designer with 4 years building small-business sites.",
        },
    ),
    (
        "client_update_writer",
        "client_update_writer.update_v1",
        {
            "progress_notes": "Homepage redesign is done; checkout is in progress.",
            "tone": "warm",
        },
    ),
    (
        "client_update_writer",
        "client_update_writer.prepaid_request_v1",
        {
            "billing_context": {
                "notes": "Design wraps up this week; development starts next.",
                "amount": "$500",
                "due_date": "Friday",
            },
            "tone": "firm",
        },
    ),
    (
        "client_update_writer",
        "client_update_writer.reply_draft_v1",
        {
            "client_message": "When will this ship?",
            "reply_goal": "State the revised date is next Wednesday.",
            "tone": "neutral",
        },
    ),
    ("brief_decoder", "brief_decoder.decode_v1", {"brief_text": BRIEF}),
    (
        "acceptance_builder",
        "acceptance_builder.draft_v1",
        {
            "brief_text": "Build a certificate generator with PDF certificates and automatic delivery by email in six weeks."
        },
    ),
    (
        "acceptance_builder",
        "acceptance_builder.check_v1",
        {
            "brief_text": "Build a certificate generator with PDF certificates and automatic delivery by email in six weeks.",
            "deliverable_text": "PDF certificates work for twelve new courses. Legacy courses are not connected yet.",
        },
    ),
)


def eventually[T](predicate: Callable[[], T], *, timeout: float = 30) -> T:
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        result = predicate()
        if result:
            return result
        sleep(0.05)
    raise AssertionError("Joint runtime condition did not become true")


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": "Bearer " + token}


def delegate(
    runtime: JointRuntime,
    client: httpx.Client,
    consumer: int = 0,
    *,
    owner_token: str | None = None,
) -> dict:
    verifier = "v" * 64
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .decode()
        .rstrip("=")
    )
    issued = client.post(
        runtime.origins["portal_api"] + "/api/backend-session-codes",
        headers=bearer(owner_token or runtime.identity.token),
        json={
            "consumer_id": runtime.consumers[consumer]["consumer_id"],
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        },
    )
    assert issued.status_code == 200, issued.text
    exchange = runtime.origins["portal_api"] + "/internal/v1/backend-sessions/exchange"
    request = {"code": issued.json()["code"], "code_verifier": verifier}
    # Invalid verifier/audience cannot redeem or consume the one-use code.
    assert (
        client.post(
            exchange,
            headers=bearer(
                runtime.consumers[consumer]["backend_to_portal_current_secret"]
            ),
            json={**request, "code_verifier": "wrong" * 13},
        ).status_code
        == 401
    )
    assert (
        client.post(
            exchange,
            headers=bearer(
                runtime.consumers[1 - consumer]["backend_to_portal_current_secret"]
            ),
            json=request,
        ).status_code
        == 401
    )
    response = client.post(
        runtime.origins["portal_api"] + "/internal/v1/backend-sessions/exchange",
        headers=bearer(runtime.consumers[consumer]["backend_to_portal_current_secret"]),
        json={"code": issued.json()["code"], "code_verifier": verifier},
    )
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    assert (
        client.post(
            exchange,
            headers=bearer(
                runtime.consumers[consumer]["backend_to_portal_current_secret"]
            ),
            json=request,
        ).status_code
        == 401
    )
    return response.json()


def rows(url: str, sql: str, parameters: dict | None = None) -> list[dict]:
    engine = create_engine(url)
    try:
        with engine.connect() as db:
            return [
                dict(row) for row in db.execute(text(sql), parameters or {}).mappings()
            ]
    finally:
        engine.dispose()


def assert_replay(reply: httpx.Response, original: dict) -> None:
    assert reply.status_code == 200, reply.text
    assert (reply.json()["scenario_session_id"], reply.json()["job_id"]) == (
        original["scenario_session_id"],
        original["job_id"],
    )


def test_real_joint_paid_execution_replay_lifecycle_and_retained_storage() -> None:
    with JointRuntime() as runtime, httpx.Client(trust_env=False, timeout=10) as client:
        portal, kernel = runtime.origins["portal_api"], runtime.origins["kernel_api"]
        user = runtime.identity.user_id
        primary = bearer(runtime.identity.token)
        delegated = delegate(runtime, client)
        auth = bearer(delegated["access_token"])
        service = bearer(runtime.consumers[0]["backend_to_portal_current_secret"])
        snapshot_path = (
            portal
            + f"/internal/v1/access-snapshots/{user}?tenant_id=anytoolai&region=ru"
        )
        snapshot = client.get(snapshot_path, headers=service)
        assert snapshot.status_code == 200, snapshot.text
        document = snapshot.json()
        assert document["schema_version"] == 3 and len(document["allowances"]) == 4, (
            document
        )
        assert {item["quantity"] for item in document["allowances"]} == {8}
        allowances = {item["product_id"]: item for item in document["allowances"]}
        # A second configured identity uses the same real Portal boundary.
        summary = delegate(runtime, client, 1)
        second_service = bearer(
            runtime.consumers[1]["backend_to_portal_current_secret"]
        )
        filtered = client.get(snapshot_path, headers=second_service)
        assert (
            filtered.status_code == 200 and len(filtered.json()["allowances"]) == 1
        ), filtered.text
        assert filtered.json()["allowances"][0]["product_id"] == "synthetic_summary"
        assert filtered.json()["access_revision"] == document["access_revision"]
        refused = client.post(
            portal + "/internal/v1/backend-sessions/introspect",
            headers=service,
            json={"access_token": summary["access_token"]},
        )
        assert refused.status_code == 401
        assert (
            client.get(
                snapshot_path.replace("region=ru", "region=eu"), headers=service
            ).status_code
            == 403
        )
        assert (
            client.get(snapshot_path, headers={**service, "Origin": portal}).status_code
            == 403
        )

        def start(case: tuple, key: str) -> httpx.Response:
            product, scenario, payload = case
            return client.post(
                kernel + f"/v1/products/{product}/scenarios/{scenario}/start",
                headers={**auth, "Idempotency-Key": key},
                json={"frontend_id": "web_mirror", "input": payload},
            )

        def revision_floor() -> int:
            # Authentication also records P for the independently scoped foreign user.
            return rows(
                runtime.kernel_url,
                "SELECT revision_floor FROM platform.paid_access_coherence "
                "WHERE consumer_id = :consumer AND tenant_id = 'anytoolai' "
                "AND region = 'ru' AND user_id = :user",
                {"consumer": runtime.kernel_consumer_id, "user": user},
            )[0]["revision_floor"]

        def finish(started: dict) -> dict:
            def completed() -> dict | None:
                response = client.get(
                    kernel + "/v1/scenario-sessions/" + started["scenario_session_id"],
                    headers=auth,
                )
                assert response.status_code == 200, response.text
                state = response.json()
                assert state["status"] not in {"failed", "cancelled"}, state
                return state if state["result_artifact_id"] else None

            state = eventually(completed)
            result = client.get(
                kernel + "/v1/results/" + state["result_artifact_id"], headers=auth
            )
            assert result.status_code == 200 and result.json()["output"]
            return state

        accepted = []
        for case in CASES:
            response = start(case, case[1])
            assert response.status_code == 200, response.text
            accepted.append(response.json())
            finish(response.json())
        foreign = delegate(runtime, client, owner_token=runtime.identity.foreign_token)
        assert (
            client.get(
                kernel + "/v1/scenario-sessions/" + accepted[0]["scenario_session_id"],
                headers=bearer(foreign["access_token"]),
            ).status_code
            == 404
        )
        empty = client.get(
            snapshot_path.replace(user, foreign["user_id"]), headers=service
        )
        assert (
            empty.status_code == 200
            and empty.json()["access_revision"] == 0
            and empty.json()["allowances"] == []
        )
        usage = client.get(portal + "/api/paid-usage", headers=primary)
        assert usage.status_code == 200, usage.text
        actual = {item["product_id"]: item for item in usage.json()["items"]}
        assert {
            product: item["successful_used"] for product, item in actual.items()
        } == {
            "proposal_ai": 1,
            "client_update_writer": 3,
            "brief_decoder": 1,
            "acceptance_builder": 2,
            "synthetic_summary": 0,
        }
        assert all(
            item["reserved"] == 0 and item["available"] == 8 - item["successful_used"]
            for item in actual.values()
        )
        delegated = delegate(
            runtime, client
        )  # Reauthorization preserves the original key/bucket.
        auth = bearer(delegated["access_token"])
        assert_replay(start(CASES[0], CASES[0][1]), accepted[0])
        event = {
            "event_id": str(uuid4()),
            "event_type": "web.product_viewed",
            "product_id": "proposal_ai",
            "frontend_id": "web_mirror",
            "web_session_id": str(uuid4()),
        }
        for _ in range(2):
            assert (
                client.post(
                    kernel + "/v1/client-events", headers=auth, json=event
                ).status_code
                == 200
            )
        assert (
            client.post(
                kernel + "/v1/client-events",
                headers=auth,
                json={**event, "event_id": str(uuid4()), "user_id": str(uuid4())},
            ).status_code
            == 422
        )
        assert (
            len(
                rows(
                    runtime.kernel_url,
                    "SELECT * FROM platform.event_log WHERE event_id = '"
                    + event["event_id"]
                    + "'",
                )
            )
            == 1
        )

        # Same-cycle blocking/restoration uses the real LBX normalization/writer/HTTP delivery.
        subscription = runtime.identity.subscriptions["proposal_ai"]

        def source(patch: dict) -> None:
            response = client.post(
                runtime.origins["lbx"]
                + f"/__test__/subscriptions/{subscription.provider_id}",
                json=patch,
            )
            assert response.status_code == 200
            runtime.command(
                runtime.portal_command("reconcile", subscription.id),
                cwd=PORTAL,
                env=runtime.portal_env,
                name="reconcile",
            )

        (runtime.run / "summary-outage").touch()
        source({"current_blocking": 1})
        eventually(lambda: revision_floor() > document["access_revision"])
        assert start(CASES[0], "blocked-new").status_code == 403
        assert_replay(start(CASES[0], CASES[0][1]), accepted[0])
        # A failing recipient cannot settle or starve the healthy recipient.
        # Kernel commits its floor before Portal records the separate ACK transaction.
        eventually(
            lambda: rows(
                runtime.portal_url,
                "SELECT 1 FROM access_invalidation_outbox "
                "WHERE recipient_id = 'platform-kernel' "
                "AND delivered_revision = pending_revision "
                f"AND delivered_revision > {document['access_revision']}",
            )
        )
        outbox = rows(
            runtime.portal_url,
            "SELECT recipient_id, pending_revision, delivered_revision FROM access_invalidation_outbox",
        )
        by_recipient = {row["recipient_id"]: row for row in outbox}
        assert (
            by_recipient["platform-kernel"]["pending_revision"]
            == by_recipient["platform-kernel"]["delivered_revision"]
        )
        assert (
            by_recipient["synthetic-summary"]["pending_revision"]
            > by_recipient["synthetic-summary"]["delivered_revision"]
        )
        (runtime.run / "summary-outage").unlink()
        eventually(
            lambda: all(
                row["pending_revision"] == row["delivered_revision"]
                for row in rows(
                    runtime.portal_url,
                    "SELECT pending_revision, delivered_revision FROM access_invalidation_outbox",
                )
            )
        )
        source({"current_blocking": 0})
        recovered = client.get(snapshot_path, headers=service).json()
        assert (
            next(
                item
                for item in recovered["allowances"]
                if item["product_id"] == "proposal_ai"
            )
            == allowances["proposal_ai"]
        )
        eventually(lambda: revision_floor() >= recovered["access_revision"])

        # A terminal external-provider failure releases capacity without a result/debit.
        (runtime.run / "provider-outage").touch()
        failed = start(CASES[4], "provider-failure")
        assert failed.status_code == 200, failed.text
        eventually(
            lambda: (
                client.get(
                    kernel
                    + "/v1/scenario-sessions/"
                    + failed.json()["scenario_session_id"],
                    headers=auth,
                ).json()["status"]
                == "failed"
            )
        )
        (runtime.run / "provider-outage").unlink()
        failure_usage = client.get(portal + "/api/paid-usage", headers=primary).json()
        brief = next(
            item
            for item in failure_usage["items"]
            if item["product_id"] == "brief_decoder"
        )
        assert (brief["successful_used"], brief["reserved"]) == (1, 0)

        # Last unit: stop only the run-owned worker so reservations remain observable.
        for number in range(6):
            response = start(CASES[0], f"fill-{number}")
            assert response.status_code == 200, response.text
            finish(response.json())
        runtime.stop("kernel-worker")
        with ThreadPoolExecutor(max_workers=2) as pool:
            contenders = list(
                pool.map(lambda key: start(CASES[0], key), ("last-a", "last-b"))
            )
        assert sorted(reply.status_code for reply in contenders) == [200, 429]
        during = client.get(portal + "/api/paid-usage", headers=primary).json()
        reserved = next(
            item for item in during["items"] if item["product_id"] == "proposal_ai"
        )
        assert (
            reserved["successful_used"],
            reserved["reserved"],
            reserved["remaining"],
            reserved["available"],
        ) == (
            7,
            1,
            1,
            0,
        )
        runtime.start(
            "kernel-worker",
            runtime.kernel_command("worker"),
            KERNEL,
            runtime.kernel_env,
        )
        finish(next(reply.json() for reply in contenders if reply.status_code == 200))
        assert start(CASES[0], "exhausted-new").status_code == 429
        eventually(
            lambda: rows(
                runtime.kernel_url,
                "SELECT * FROM platform.allowance_exhaustion_outbox WHERE state = 'delivered'",
            )
        )
        hints = rows(
            runtime.portal_url,
            "SELECT * FROM billing_work_items WHERE work_kind = 'allowance_exhaustion'",
        )
        assert len(hints) == 1

        # Reverse API routing and durable deduplication for the synthetic owner.
        summary_allowance = filtered.json()["allowances"][0]
        exhaustion = {
            "schema_version": 1,
            "event_type": "allowance_exhausted",
            "tenant_id": "anytoolai",
            "region": "ru",
            "user_id": user,
            **summary_allowance,
            "occurred_at": datetime.now(UTC).isoformat(),
        }
        endpoint = portal + "/internal/v1/allowance-exhaustions"
        assert (
            client.post(endpoint, headers=service, json=exhaustion).status_code == 403
        )
        for _ in range(2):
            assert (
                client.post(
                    endpoint, headers=second_service, json=exhaustion
                ).status_code
                == 204
            )
        assert (
            client.post(
                endpoint, headers=second_service, json={**exhaustion, "quantity": 9}
            ).status_code
            == 409
        )
        assert (
            len(
                rows(
                    runtime.portal_url,
                    "SELECT * FROM billing_work_items WHERE work_kind = 'allowance_exhaustion'",
                )
            )
            == 2
        )
        assert any(
            json.loads(line)["path"].startswith("/internal/v1/usage/")
            for line in (runtime.run / "summary-requests.jsonl")
            .read_text()
            .splitlines()
        )

        # Only authoritative new-cycle evidence produces a fresh bucket; replay stays old.
        now = datetime.now(UTC)
        source(
            {
                "last_tariffication_period_start": f"{now.year}-{now.month:02}-01",
                "last_tariffication_period_end": f"{now.year}-{now.month:02}-{monthrange(now.year, now.month)[1]}",
            }
        )
        renewed = client.get(snapshot_path, headers=service).json()
        new_bucket = next(
            item
            for item in renewed["allowances"]
            if item["product_id"] == "proposal_ai"
        )
        assert (
            new_bucket["allowance_id"] != allowances["proposal_ai"]["allowance_id"]
            and new_bucket["quantity"] == 8
        )
        eventually(lambda: revision_floor() >= renewed["access_revision"])
        assert_replay(start(CASES[0], CASES[0][1]), accepted[0])
        new_execution = start(CASES[0], "new-cycle")
        assert new_execution.status_code == 200, new_execution.text
        finish(new_execution.json())

        # Policy-only cutover changes P and not paid R or historical purchase meaning.
        runtime.stop("portal-api")
        runtime.consumers[1]["consumer_policy_revision"] = 2
        runtime.consumers[1]["allowed_products"] = [
            "synthetic_summary",
            "synthetic_extra",
        ]
        runtime.portal_env["BACKEND_CONSUMERS"] = json.dumps(runtime.consumers)

        # Recreate both database containers against their original run-owned named volumes.
        runtime.stop("kernel-worker")
        runtime.stop("kernel-api")
        runtime.stop("portal-api")
        saved = {
            "purchases": rows(
                runtime.portal_url,
                "SELECT purchase_intent_id, accepted_snapshot::text FROM purchase_intents ORDER BY purchase_intent_id",
            ),
            "usage": rows(
                runtime.kernel_url,
                "SELECT * FROM platform.paid_allowance_usage ORDER BY allowance_id",
            ),
            "floor": rows(
                runtime.kernel_url,
                "SELECT * FROM platform.paid_access_coherence ORDER BY user_id",
            ),
        }
        for owner in ("portal", "kernel"):
            runtime.compose(
                owner,
                "up",
                "-d",
                "--pull",
                "never",
                "--force-recreate",
                "--wait",
                "postgres",
            )
        assert (
            rows(
                runtime.portal_url,
                "SELECT purchase_intent_id, accepted_snapshot::text FROM purchase_intents ORDER BY purchase_intent_id",
            )
            == saved["purchases"]
        )
        assert (
            rows(
                runtime.kernel_url,
                "SELECT * FROM platform.paid_allowance_usage ORDER BY allowance_id",
            )
            == saved["usage"]
        )
        assert (
            rows(
                runtime.kernel_url,
                "SELECT * FROM platform.paid_access_coherence ORDER BY user_id",
            )
            == saved["floor"]
        )
        runtime.start(
            "kernel-api", runtime.kernel_command("api"), KERNEL, runtime.kernel_env
        )
        runtime.wait(kernel + "/health", name="kernel-api")
        runtime.start(
            "portal-api",
            [
                str(PORTAL / ".venv/bin/python"),
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(runtime.ports["portal_api"]),
                "--no-access-log",
            ],
            PORTAL,
            runtime.portal_env,
        )
        runtime.wait(portal + "/api/auth/session", name="portal-api")
        policy = client.get(snapshot_path, headers=second_service).json()
        assert (
            policy["consumer_policy_revision"] == 2
            and policy["access_revision"] == renewed["access_revision"]
        )
        assert (
            client.get(snapshot_path, headers=service).json()[
                "consumer_policy_revision"
            ]
            == 1
        )
        assert_replay(start(CASES[0], CASES[0][1]), accepted[0])
        logout = client.post(portal + "/api/auth/logout", headers=primary)
        assert logout.status_code in {200, 204}, logout.text
        assert start(CASES[0], "revoked-parent").status_code == 401


def test_review_policy_cutover_preserves_accepted_work_and_recipient_history() -> None:
    with (
        JointRuntime(kernel_consumer_id="custom-kernel") as runtime,
        httpx.Client(trust_env=False, timeout=10) as client,
    ):
        portal, kernel = runtime.origins["portal_api"], runtime.origins["kernel_api"]
        auth = bearer(delegate(runtime, client)["access_token"])
        service = bearer(runtime.consumers[0]["backend_to_portal_current_secret"])
        snapshot_url = (
            portal
            + f"/internal/v1/access-snapshots/{runtime.identity.user_id}?tenant_id=anytoolai&region=ru"
        )
        original = client.get(snapshot_url, headers=service).json()
        assert original["consumer_id"] == "custom-kernel"
        purchases_before = rows(
            runtime.portal_url,
            "SELECT purchase_intent_id, accepted_snapshot::text FROM purchase_intents ORDER BY purchase_intent_id",
        )
        product, scenario, payload = CASES[0]

        def start(key: str) -> httpx.Response:
            return client.post(
                kernel + f"/v1/products/{product}/scenarios/{scenario}/start",
                headers={**auth, "Idempotency-Key": key},
                json={"frontend_id": "web_mirror", "input": payload},
            )

        def restart_portal(consumers: list[dict]) -> None:
            runtime.stop("portal-api")
            runtime.portal_env["BACKEND_CONSUMERS"] = json.dumps(consumers)
            runtime.start(
                "portal-api",
                [
                    str(PORTAL / ".venv/bin/python"),
                    "-m",
                    "uvicorn",
                    "app.main:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(runtime.ports["portal_api"]),
                    "--no-access-log",
                    "--log-level",
                    "warning",
                ],
                PORTAL,
                runtime.portal_env,
            )
            runtime.wait(portal + "/api/auth/session", name="portal-api")

        def usage() -> list[dict]:
            return rows(
                runtime.kernel_url,
                "SELECT * FROM platform.paid_allowance_usage ORDER BY allowance_id",
            )

        runtime.stop("kernel-worker")
        response = start("accepted-before-policy")
        assert response.status_code == 200, response.text
        accepted = response.json()
        reserved = usage()
        original_permissions = runtime.consumers[0]["permissions"][:]
        runtime.consumers[0]["consumer_policy_revision"] = 2
        runtime.consumers[0]["permissions"].remove("access-snapshot:read")
        restart_portal(runtime.consumers)
        denied = start("denied-after-policy")
        assert denied.status_code == 503, denied.text
        assert usage() == reserved
        assert_replay(start("accepted-before-policy"), accepted)
        runtime.start(
            "kernel-worker",
            runtime.kernel_command("worker"),
            KERNEL,
            runtime.kernel_env,
        )

        def completed() -> dict | None:
            reply = client.get(
                kernel + "/v1/scenario-sessions/" + accepted["scenario_session_id"],
                headers=auth,
            )
            assert reply.status_code == 200, reply.text
            body = reply.json()
            assert body["status"] not in {"failed", "cancelled"}, body
            return body if body["result_artifact_id"] else None

        result = eventually(completed)
        assert (
            client.get(
                kernel + "/v1/results/" + result["result_artifact_id"], headers=auth
            ).status_code
            == 200
        )
        finished_usage = usage()
        assert_replay(start("accepted-before-policy"), accepted)
        assert usage() == finished_usage
        runtime.consumers[0]["consumer_policy_revision"] = 3
        runtime.consumers[0]["permissions"] = original_permissions
        restart_portal(runtime.consumers)
        restored = client.get(snapshot_url, headers=service).json()
        assert restored["consumer_policy_revision"] == 3
        for field in ("access_revision", "grants", "allowances"):
            assert restored[field] == original[field]
        assert usage() == finished_usage
        actual = client.get(
            portal + "/api/paid-usage", headers=bearer(runtime.identity.token)
        ).json()
        item = next(item for item in actual["items"] if item["product_id"] == product)
        assert (item["successful_used"], item["reserved"]) == (1, 0)

        subscription = runtime.identity.subscriptions[product]

        def source(blocked: int) -> None:
            reply = client.post(
                runtime.origins["lbx"]
                + f"/__test__/subscriptions/{subscription.provider_id}",
                json={"current_blocking": blocked},
            )
            assert reply.status_code == 200
            runtime.command(
                runtime.portal_command("reconcile", subscription.id),
                cwd=PORTAL,
                env=runtime.portal_env,
                name="review-reconcile",
            )

        (runtime.run / "summary-outage").touch()
        source(1)
        runtime.stop("portal-api")
        history_sql = "SELECT * FROM access_invalidation_outbox WHERE recipient_id='synthetic-summary'"
        retained = rows(runtime.portal_url, history_sql)
        assert retained[0]["pending_revision"] > retained[0]["delivered_revision"]
        # Fault injection affects only this run's disposable scheduling row.
        engine = create_engine(runtime.portal_url)
        try:
            with engine.begin() as db:
                db.execute(
                    text(
                        "DELETE FROM billing_work_items WHERE work_kind='access_invalidation' AND recipient_id='synthetic-summary'"
                    )
                )
        finally:
            engine.dispose()
        restart_portal(runtime.consumers[:1])
        source(0)
        assert rows(runtime.portal_url, history_sql) == retained
        assert (
            rows(
                runtime.portal_url,
                "SELECT 1 FROM billing_work_items WHERE work_kind='access_invalidation' AND recipient_id='synthetic-summary'",
            )
            == []
        )
        (runtime.run / "summary-outage").unlink()
        runtime.consumers[1]["consumer_policy_revision"] = 2
        restart_portal(runtime.consumers)
        eventually(
            lambda: (
                rows(runtime.portal_url, history_sql)[0]["delivered_revision"]
                == retained[0]["pending_revision"]
            )
        )
        assert usage() == finished_usage
        assert (
            rows(
                runtime.portal_url,
                "SELECT purchase_intent_id, accepted_snapshot::text FROM purchase_intents ORDER BY purchase_intent_id",
            )
            == purchases_before
        )
        (runtime.run / "review-corrections.json").write_text(
            json.dumps(
                {
                    "custom_consumer": runtime.kernel_consumer_id,
                    "policy_revisions": [1, 2, 3],
                    "accepted_session": accepted["scenario_session_id"],
                    "successful_used": 1,
                    "purchase_history_preserved": True,
                    "retired_recipient_repaired_after_return": True,
                },
                indent=2,
            )
        )
