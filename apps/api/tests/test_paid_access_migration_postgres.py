"""Forward/backward migration evidence on real disposable PostgreSQL."""

from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy import select, text
from sqlalchemy.engine import Engine, URL
from sqlalchemy.exc import DatabaseError
from sqlalchemy.orm import Session, sessionmaker

from apps.api.tests.support.postgres import alembic_test_config
from apps.api.tests.factories.paid_access import AcceptedSubscription
from app.domains.purchases.evidence import accepted
from app.models import PurchaseIntent
from app.domains.billing.paid_allowances import materialize_allowance
from app.models import BillingProductAccessScope, ExternalSubscription
from apps.api.tests.test_paid_access_terms_postgres import calendar

pytestmark = [pytest.mark.postgres, pytest.mark.anyio]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def test_paid_access_migration_preserves_legacy_utc_without_calendar_inference(
    paid_terms_scenario: AcceptedSubscription, postgres_engine: Engine, database_test_url: URL
) -> None:
    identity = uuid4()
    with alembic_test_config(database_test_url) as config:
        command.downgrade(config, "20261028_0005")
        with postgres_engine.begin() as connection:
            connection.execute(
                text("""INSERT INTO purchased_allowances
                (allowance_id, subscription_id, source_component_id, product_id, metric_key, quantity,
                 provider_cycle_key, period_start, period_end)
                VALUES (:id, :sub, '1001', 'proposal_ai', 'proposal_ai.test_generations', 17,
                        'legacy-cycle', '2026-01-01T12:34:56.123456Z', '2026-02-01T12:34:56.123456Z')"""),
                {"id": identity, "sub": paid_terms_scenario.subscription_id},
            )
            before = connection.execute(text("SELECT to_jsonb(a) FROM purchased_allowances a")).scalar_one()
        command.upgrade(config, "head")
        with postgres_engine.connect() as connection:
            after = connection.execute(text("SELECT to_jsonb(a) FROM purchased_allowances a")).scalar_one()
            assert after == {
                **before,
                "cycle_schema_version": "legacy-utc:v1",
                "cycle_date_start": None,
                "cycle_date_end": None,
                "calendar_document": None,
                "unit": None,
                "terms_document": None,
            }
        command.downgrade(config, "20261028_0005")
        with postgres_engine.connect() as connection:
            assert connection.execute(text("SELECT to_jsonb(a) FROM purchased_allowances a")).scalar_one() == before
        command.upgrade(config, "head")


@pytest.mark.parametrize("bad", ["duplicates", "state_zero", "observation_zero", "outbox_negative"])
async def test_paid_access_migration_preflight_refuses_incompatible_history(
    paid_terms_scenario: AcceptedSubscription, postgres_engine: Engine, database_test_url: URL, bad: str
) -> None:
    with alembic_test_config(database_test_url) as config:
        command.downgrade(config, "20261028_0005")
        with postgres_engine.begin() as connection:
            if bad == "duplicates":
                for _ in range(2):
                    connection.execute(
                        text("""INSERT INTO purchased_allowances
                      (allowance_id, subscription_id, source_component_id, product_id, metric_key, quantity, provider_cycle_key, period_start, period_end)
                      VALUES (:id,:sub,'component','proposal_ai','metric',1,'duplicate',now(),now()+interval '1 day')"""),
                        {"id": uuid4(), "sub": paid_terms_scenario.subscription_id},
                    )
                table = "purchased_allowances"
            elif bad == "state_zero":
                connection.execute(
                    text("""INSERT INTO paid_access_states
                  (paid_access_state_id,tenant_id,region,user_id,access_revision,effective_state_schema_version,effective_state_document,committed_at)
                  VALUES (:id,'anytoolai','ru',:user,0,'legacy','{}',now())"""),
                    {"id": uuid4(), "user": paid_terms_scenario.user_id},
                )
                table = "paid_access_states"
            elif bad == "observation_zero":
                connection.execute(
                    text("""INSERT INTO billing_state_observations
                  (observation_id,observation_kind,external_billing_account_id,user_id,product_id,subscription_id,observed_at,evidence_schema_version,evidence_document,completeness_classification,result_classification,resulting_access_revision)
                  SELECT :id,'authoritative_subscription_read',external_billing_account_id,user_id,product_id,subscription_id,now(),'legacy','{}','complete','test',0
                  FROM external_subscriptions LIMIT 1"""),
                    {"id": uuid4()},
                )
                table = "billing_state_observations"
            else:
                connection.execute(
                    text("""INSERT INTO access_invalidation_outbox
                  (outbox_id,tenant_id,region,user_id,pending_revision,delivered_revision,next_attempt_at)
                  VALUES (:id,'anytoolai','ru',:user,1,-1,now())"""),
                    {"id": uuid4(), "user": paid_terms_scenario.user_id},
                )
                table = "access_invalidation_outbox"
            before = connection.execute(
                text(f"SELECT jsonb_agg(to_jsonb(t) ORDER BY to_jsonb(t)::text) FROM {table} t")
            ).scalar_one()
        with pytest.raises(DatabaseError, match="incompatible legacy evidence"):
            command.upgrade(config, "head")
        with postgres_engine.connect() as connection:
            assert (
                connection.execute(
                    text(f"SELECT jsonb_agg(to_jsonb(t) ORDER BY to_jsonb(t)::text) FROM {table} t")
                ).scalar_one()
                == before
            )
            assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "20261028_0005"


@pytest.mark.parametrize("paid_terms_scenario", ["proposal_ai"], indirect=True)
async def test_paid_access_migration_preserves_existing_v2_purchase(
    paid_terms_scenario: AcceptedSubscription,
    postgres_engine: Engine,
    postgres_session_factory: sessionmaker[Session],
    database_test_url: URL,
) -> None:
    with alembic_test_config(database_test_url) as config:
        command.downgrade(config, "20261028_0005")
        with postgres_engine.connect() as connection:
            before = connection.execute(text("SELECT to_jsonb(p) FROM purchase_intents p")).scalar_one()
        command.upgrade(config, "head")
        with postgres_engine.connect() as connection:
            assert connection.execute(text("SELECT to_jsonb(p) FROM purchase_intents p")).scalar_one() == before
    with postgres_session_factory() as db:
        saved = accepted(db.scalars(select(PurchaseIntent)).one())
        assert saved == paid_terms_scenario.accepted and saved.schema_version == "accepted-purchase:v2"


@pytest.mark.parametrize("paid_terms_scenario", ["proposal_ai"], indirect=True)
@pytest.mark.parametrize("meaning", ["calendar", "state", "retired_primary"])
async def test_paid_access_migration_downgrade_refuses_loss_of_calendar_and_access(
    paid_terms_scenario: AcceptedSubscription,
    postgres_session_factory: sessionmaker[Session],
    database_test_url: URL,
    meaning: str,
) -> None:
    scenario = paid_terms_scenario
    with postgres_session_factory() as db:
        if meaning == "calendar":
            sub = db.get(ExternalSubscription, scenario.subscription_id)
            assert materialize_allowance(db, sub, scenario.accepted, calendar(), skew_seconds=10) is not None
        elif meaning == "state":
            db.execute(
                text("""INSERT INTO paid_access_states
                (paid_access_state_id,tenant_id,region,user_id,access_revision,effective_state_schema_version,effective_state_document,committed_at)
                VALUES (:id,'anytoolai','ru',:user,1,'paid-effective-state:v1','{}',now())"""),
                {"id": uuid4(), "user": scenario.user_id},
            )
        else:
            from datetime import UTC, datetime

            db.add(
                BillingProductAccessScope(
                    user_id=scenario.user_id,
                    product_id=scenario.accepted.meaning.product_id,
                    primary_retired_at=datetime.now(UTC),
                )
            )
        db.commit()
    with alembic_test_config(database_test_url) as config:
        with pytest.raises(DatabaseError, match="refuses to discard committed calendar/access meaning"):
            command.downgrade(config, "20261028_0005")


@pytest.mark.parametrize("paid_terms_scenario", ["proposal_ai"], indirect=True)
async def test_paid_access_migration_keeps_history_immutable_and_revisions_monotonic(
    paid_terms_scenario: AcceptedSubscription,
    postgres_engine: Engine,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    scenario = paid_terms_scenario
    with postgres_session_factory() as db:
        sub = db.get(ExternalSubscription, scenario.subscription_id)
        materialize_allowance(db, sub, scenario.accepted, calendar(), skew_seconds=10)
        db.execute(
            text("""INSERT INTO paid_access_states
            (paid_access_state_id,tenant_id,region,user_id,access_revision,effective_state_schema_version,effective_state_document,committed_at)
            VALUES (:id,'anytoolai','ru',:user,1,'paid-effective-state:v1','{}',now())"""),
            {"id": uuid4(), "user": scenario.user_id},
        )
        db.execute(
            text("""INSERT INTO access_invalidation_outbox
            (outbox_id,recipient_id,tenant_id,region,user_id,pending_revision,delivered_revision,next_attempt_at)
            VALUES (:id,'platform-kernel','anytoolai','ru',:user,1,0,now())"""),
            {"id": uuid4(), "user": scenario.user_id},
        )
        db.commit()
    for statement in (
        "UPDATE purchased_allowances SET quantity=101",
        "DELETE FROM purchased_allowances",
        "UPDATE purchase_intents SET accepted_snapshot='{}'",
        "UPDATE paid_access_states SET access_revision=0",
        "UPDATE paid_access_states SET access_revision=3",
        "UPDATE paid_access_states SET effective_state_document='{\"grants\":[]}'",
        "DELETE FROM paid_access_states",
        "UPDATE access_invalidation_outbox SET pending_revision=0",
        "UPDATE access_invalidation_outbox SET delivered_revision=-1",
        "UPDATE access_invalidation_outbox SET delivered_revision=2",
        "DELETE FROM access_invalidation_outbox",
    ):
        with pytest.raises(DatabaseError), postgres_engine.begin() as connection:
            connection.execute(text(statement))
    with postgres_engine.begin() as connection:
        assert connection.execute(text("SELECT quantity FROM purchased_allowances")).scalar_one() == 100
        assert connection.execute(text("SELECT access_revision FROM paid_access_states")).scalar_one() == 1
        assert connection.execute(text("SELECT pending_revision FROM access_invalidation_outbox")).scalar_one() == 1
        connection.execute(
            text("UPDATE paid_access_states SET access_revision=2,effective_state_document='{\"grants\":[]}'")
        )
        connection.execute(text("UPDATE access_invalidation_outbox SET pending_revision=2,delivered_revision=1"))
