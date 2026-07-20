"""catalog, plans, bundles, limits, and deterministic seed data

Revision ID: 20260707_0002
Revises: 20260707_0001
Create Date: 2026-07-07
"""

from __future__ import annotations

from uuid import UUID

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260707_0002"
down_revision = "20260707_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    uuid_type = sa.Uuid()

    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")

    op.create_table(
        "products",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False, server_default=sa.text("'anytoolai'")),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("platform_product_id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'active'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("tenant_id", "code", name="uq_products_tenant_code"),
        sa.UniqueConstraint(
            "tenant_id",
            "platform_product_id",
            name="uq_products_tenant_platform_product_id",
        ),
    )
    op.create_index("ix_products_code", "products", ["code"])
    op.create_index("ix_products_status", "products", ["status"])
    op.create_index("ix_products_tenant_id", "products", ["tenant_id"])
    op.create_index("ix_products_tenant_status", "products", ["tenant_id", "status"])

    op.create_table(
        "bundles",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False, server_default=sa.text("'anytoolai'")),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'active'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("tenant_id", "code", name="uq_bundles_tenant_code"),
    )
    op.create_index("ix_bundles_code", "bundles", ["code"])
    op.create_index("ix_bundles_status", "bundles", ["status"])
    op.create_index("ix_bundles_tenant_id", "bundles", ["tenant_id"])
    op.create_index("ix_bundles_tenant_status", "bundles", ["tenant_id", "status"])

    op.create_table(
        "bundle_products",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False, server_default=sa.text("'anytoolai'")),
        sa.Column("bundle_id", uuid_type, sa.ForeignKey("bundles.id"), nullable=False),
        sa.Column("product_id", uuid_type, sa.ForeignKey("products.id"), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'active'")),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_bundle_products_tenant_id", "bundle_products", ["tenant_id"])
    op.create_index(
        "ix_bundle_products_bundle_status",
        "bundle_products",
        ["bundle_id", "status"],
    )
    op.create_index("ix_bundle_products_product_id", "bundle_products", ["product_id"])
    op.create_index(
        "uq_bundle_products_active_product",
        "bundle_products",
        ["bundle_id", "product_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active' AND valid_to IS NULL"),
    )

    op.create_table(
        "plans",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False, server_default=sa.text("'anytoolai'")),
        sa.Column("region", sa.Text(), sa.ForeignKey("regions.code"), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("scope_type", sa.Text(), nullable=False),
        sa.Column("product_id", uuid_type, sa.ForeignKey("products.id"), nullable=True),
        sa.Column("bundle_id", uuid_type, sa.ForeignKey("bundles.id"), nullable=True),
        sa.Column("price_amount_minor", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("billing_period", sa.Text(), nullable=False),
        sa.Column("renewal_mode", sa.Text(), nullable=False, server_default=sa.text("'manual'")),
        sa.Column("trial_days", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'active'")),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "scope_type IN ('product', 'bundle', 'all_access')",
            name="ck_plans_scope_type",
        ),
        sa.CheckConstraint("price_amount_minor >= 0", name="ck_plans_price_non_negative"),
        sa.CheckConstraint("trial_days >= 0", name="ck_plans_trial_days_non_negative"),
        sa.CheckConstraint(
            "valid_to IS NULL OR valid_to > valid_from",
            name="ck_plans_valid_window",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "region",
            "code",
            "valid_from",
            name="uq_plans_tenant_region_code_valid_from",
        ),
    )
    op.create_index("ix_plans_code", "plans", ["code"])
    op.create_index("ix_plans_region", "plans", ["region"])
    op.create_index("ix_plans_region_status", "plans", ["region", "status"])
    op.create_index("ix_plans_status", "plans", ["status"])
    op.create_index("ix_plans_tenant_id", "plans", ["tenant_id"])
    op.create_index("ix_plans_product_id", "plans", ["product_id"])
    op.create_index("ix_plans_bundle_id", "plans", ["bundle_id"])
    op.create_index(
        "uq_plans_active_code",
        "plans",
        ["tenant_id", "region", "code"],
        unique=True,
        postgresql_where=sa.text("status = 'active' AND valid_to IS NULL"),
    )
    op.execute(
        """
        ALTER TABLE plans
        ADD CONSTRAINT ex_plans_active_version_overlap
        EXCLUDE USING gist (
            tenant_id WITH =,
            region WITH =,
            code WITH =,
            tstzrange(valid_from, COALESCE(valid_to, 'infinity'::timestamptz), '[)') WITH &&
        )
        WHERE (status = 'active')
        """
    )

    op.create_table(
        "plan_price_components",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("plan_id", uuid_type, sa.ForeignKey("plans.id"), nullable=False),
        sa.Column("component_type", sa.Text(), nullable=False),
        sa.Column("source_product_id", uuid_type, sa.ForeignKey("products.id"), nullable=True),
        sa.Column("source_bundle_id", uuid_type, sa.ForeignKey("bundles.id"), nullable=True),
        sa.Column("source_plan_id", uuid_type, sa.ForeignKey("plans.id"), nullable=True),
        sa.Column("component_code_snapshot", sa.Text(), nullable=False),
        sa.Column("title_snapshot", sa.Text(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("list_amount_minor", sa.Integer(), nullable=False),
        sa.Column("discount_amount_minor", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("amount_minor", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("quantity > 0", name="ck_plan_price_components_quantity_positive"),
        sa.CheckConstraint(
            "list_amount_minor >= 0 AND discount_amount_minor >= 0 AND amount_minor >= 0",
            name="ck_plan_price_components_amounts_non_negative",
        ),
    )
    op.create_index(
        "ix_plan_price_components_plan_position",
        "plan_price_components",
        ["plan_id", "position"],
    )
    op.create_index(
        "ix_plan_price_components_source_plan_id",
        "plan_price_components",
        ["source_plan_id"],
    )

    op.create_table(
        "plan_limits",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("plan_id", uuid_type, sa.ForeignKey("plans.id"), nullable=False),
        sa.Column("product_id", uuid_type, sa.ForeignKey("products.id"), nullable=True),
        sa.Column("metric", sa.Text(), nullable=False),
        sa.Column("limit_count", sa.Integer(), nullable=False),
        sa.Column("period", sa.Text(), nullable=False),
        sa.Column("reset_policy", sa.Text(), nullable=False, server_default=sa.text("'billing_period'")),
        sa.Column("overage_policy", sa.Text(), nullable=False, server_default=sa.text("'deny'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("limit_count >= 0", name="ck_plan_limits_limit_count_non_negative"),
        sa.UniqueConstraint("plan_id", "metric", name="uq_plan_limits_plan_metric"),
    )
    op.create_index("ix_plan_limits_plan_id", "plan_limits", ["plan_id"])
    op.create_index("ix_plan_limits_metric", "plan_limits", ["metric"])

    op.bulk_insert(
        sa.table(
            "products",
            sa.column("id", uuid_type),
            sa.column("tenant_id", sa.Text()),
            sa.column("code", sa.Text()),
            sa.column("platform_product_id", sa.Text()),
            sa.column("name", sa.Text()),
            sa.column("description", sa.Text()),
            sa.column("status", sa.Text()),
        ),
        [
            {
                "id": UUID("66666666-6666-4666-8666-666666666601"),
                "tenant_id": "anytoolai",
                "code": "document-summary",
                "platform_product_id": "document-summary",
                "name": "Document Summary",
                "description": "Chrome extension for document and web page summaries.",
                "status": "active",
            },
            {
                "id": UUID("66666666-6666-4666-8666-666666666602"),
                "tenant_id": "anytoolai",
                "code": "prompt-optimizer",
                "platform_product_id": "prompt-optimizer",
                "name": "Prompt Optimizer",
                "description": "Chrome extension for improving AI prompts.",
                "status": "active",
            },
        ],
    )
    op.bulk_insert(
        sa.table(
            "bundles",
            sa.column("id", uuid_type),
            sa.column("tenant_id", sa.Text()),
            sa.column("code", sa.Text()),
            sa.column("name", sa.Text()),
            sa.column("description", sa.Text()),
            sa.column("status", sa.Text()),
        ),
        [
            {
                "id": UUID("77777777-7777-4777-8777-777777777701"),
                "tenant_id": "anytoolai",
                "code": "core-tools-bundle",
                "name": "Core Tools Bundle",
                "description": "Document Summary and Prompt Optimizer bundle.",
                "status": "active",
            },
        ],
    )
    op.bulk_insert(
        sa.table(
            "bundle_products",
            sa.column("id", uuid_type),
            sa.column("tenant_id", sa.Text()),
            sa.column("bundle_id", uuid_type),
            sa.column("product_id", uuid_type),
            sa.column("status", sa.Text()),
        ),
        [
            {
                "id": UUID("88888888-8888-4888-8888-888888888801"),
                "tenant_id": "anytoolai",
                "bundle_id": UUID("77777777-7777-4777-8777-777777777701"),
                "product_id": UUID("66666666-6666-4666-8666-666666666601"),
                "status": "active",
            },
            {
                "id": UUID("88888888-8888-4888-8888-888888888802"),
                "tenant_id": "anytoolai",
                "bundle_id": UUID("77777777-7777-4777-8777-777777777701"),
                "product_id": UUID("66666666-6666-4666-8666-666666666602"),
                "status": "active",
            },
        ],
    )
    op.bulk_insert(
        sa.table(
            "plans",
            sa.column("id", uuid_type),
            sa.column("tenant_id", sa.Text()),
            sa.column("region", sa.Text()),
            sa.column("code", sa.Text()),
            sa.column("name", sa.Text()),
            sa.column("scope_type", sa.Text()),
            sa.column("product_id", uuid_type),
            sa.column("bundle_id", uuid_type),
            sa.column("price_amount_minor", sa.Integer()),
            sa.column("currency", sa.String(length=3)),
            sa.column("billing_period", sa.Text()),
            sa.column("renewal_mode", sa.Text()),
            sa.column("trial_days", sa.Integer()),
            sa.column("status", sa.Text()),
            sa.column("metadata", postgresql.JSONB(astext_type=sa.Text())),
        ),
        [
            {
                "id": UUID("99999999-9999-4999-8999-999999999901"),
                "tenant_id": "anytoolai",
                "region": "ru",
                "code": "document-summary-pro",
                "name": "Document Summary Pro",
                "scope_type": "product",
                "product_id": UUID("66666666-6666-4666-8666-666666666601"),
                "bundle_id": None,
                "price_amount_minor": 99000,
                "currency": "RUB",
                "billing_period": "month",
                "renewal_mode": "manual",
                "trial_days": 7,
                "status": "active",
                "metadata": {},
            },
            {
                "id": UUID("99999999-9999-4999-8999-999999999902"),
                "tenant_id": "anytoolai",
                "region": "ru",
                "code": "prompt-optimizer-pro",
                "name": "Prompt Optimizer Pro",
                "scope_type": "product",
                "product_id": UUID("66666666-6666-4666-8666-666666666602"),
                "bundle_id": None,
                "price_amount_minor": 99000,
                "currency": "RUB",
                "billing_period": "month",
                "renewal_mode": "manual",
                "trial_days": 7,
                "status": "active",
                "metadata": {},
            },
            {
                "id": UUID("99999999-9999-4999-8999-999999999903"),
                "tenant_id": "anytoolai",
                "region": "ru",
                "code": "core-tools-bundle-pro-ru",
                "name": "Core Tools Bundle Pro RU",
                "scope_type": "bundle",
                "product_id": None,
                "bundle_id": UUID("77777777-7777-4777-8777-777777777701"),
                "price_amount_minor": 198000,
                "currency": "RUB",
                "billing_period": "month",
                "renewal_mode": "manual",
                "trial_days": 7,
                "status": "active",
                "metadata": {},
            },
            {
                "id": UUID("99999999-9999-4999-8999-999999999904"),
                "tenant_id": "anytoolai",
                "region": "ru",
                "code": "all-access-pro-ru",
                "name": "All Access Pro RU",
                "scope_type": "all_access",
                "product_id": None,
                "bundle_id": None,
                "price_amount_minor": 198000,
                "currency": "RUB",
                "billing_period": "month",
                "renewal_mode": "manual",
                "trial_days": 7,
                "status": "active",
                "metadata": {"included_product_codes": ["document-summary", "prompt-optimizer"]},
            },
        ],
    )
    op.bulk_insert(
        sa.table(
            "plan_price_components",
            sa.column("id", uuid_type),
            sa.column("plan_id", uuid_type),
            sa.column("component_type", sa.Text()),
            sa.column("source_product_id", uuid_type),
            sa.column("source_plan_id", uuid_type),
            sa.column("component_code_snapshot", sa.Text()),
            sa.column("title_snapshot", sa.Text()),
            sa.column("quantity", sa.Integer()),
            sa.column("list_amount_minor", sa.Integer()),
            sa.column("discount_amount_minor", sa.Integer()),
            sa.column("amount_minor", sa.Integer()),
            sa.column("currency", sa.String(length=3)),
            sa.column("position", sa.Integer()),
            sa.column("metadata", postgresql.JSONB(astext_type=sa.Text())),
        ),
        [
            {
                "id": UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1"),
                "plan_id": UUID("99999999-9999-4999-8999-999999999903"),
                "component_type": "product_plan",
                "source_product_id": UUID("66666666-6666-4666-8666-666666666601"),
                "source_plan_id": UUID("99999999-9999-4999-8999-999999999901"),
                "component_code_snapshot": "document-summary-pro",
                "title_snapshot": "Document Summary Pro",
                "quantity": 1,
                "list_amount_minor": 99000,
                "discount_amount_minor": 0,
                "amount_minor": 99000,
                "currency": "RUB",
                "position": 1,
                "metadata": {},
            },
            {
                "id": UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa2"),
                "plan_id": UUID("99999999-9999-4999-8999-999999999903"),
                "component_type": "product_plan",
                "source_product_id": UUID("66666666-6666-4666-8666-666666666602"),
                "source_plan_id": UUID("99999999-9999-4999-8999-999999999902"),
                "component_code_snapshot": "prompt-optimizer-pro",
                "title_snapshot": "Prompt Optimizer Pro",
                "quantity": 1,
                "list_amount_minor": 99000,
                "discount_amount_minor": 0,
                "amount_minor": 99000,
                "currency": "RUB",
                "position": 2,
                "metadata": {},
            },
            {
                "id": UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa3"),
                "plan_id": UUID("99999999-9999-4999-8999-999999999904"),
                "component_type": "product_plan",
                "source_product_id": UUID("66666666-6666-4666-8666-666666666601"),
                "source_plan_id": UUID("99999999-9999-4999-8999-999999999901"),
                "component_code_snapshot": "document-summary-pro",
                "title_snapshot": "Document Summary Pro",
                "quantity": 1,
                "list_amount_minor": 99000,
                "discount_amount_minor": 0,
                "amount_minor": 99000,
                "currency": "RUB",
                "position": 1,
                "metadata": {},
            },
            {
                "id": UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa4"),
                "plan_id": UUID("99999999-9999-4999-8999-999999999904"),
                "component_type": "product_plan",
                "source_product_id": UUID("66666666-6666-4666-8666-666666666602"),
                "source_plan_id": UUID("99999999-9999-4999-8999-999999999902"),
                "component_code_snapshot": "prompt-optimizer-pro",
                "title_snapshot": "Prompt Optimizer Pro",
                "quantity": 1,
                "list_amount_minor": 99000,
                "discount_amount_minor": 0,
                "amount_minor": 99000,
                "currency": "RUB",
                "position": 2,
                "metadata": {},
            },
        ],
    )
    op.bulk_insert(
        sa.table(
            "plan_limits",
            sa.column("id", uuid_type),
            sa.column("plan_id", uuid_type),
            sa.column("product_id", uuid_type),
            sa.column("metric", sa.Text()),
            sa.column("limit_count", sa.Integer()),
            sa.column("period", sa.Text()),
            sa.column("reset_policy", sa.Text()),
            sa.column("overage_policy", sa.Text()),
        ),
        [
            {
                "id": UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb1"),
                "plan_id": UUID("99999999-9999-4999-8999-999999999901"),
                "product_id": UUID("66666666-6666-4666-8666-666666666601"),
                "metric": "document_summary_runs",
                "limit_count": 1000,
                "period": "month",
                "reset_policy": "billing_period",
                "overage_policy": "deny",
            },
            {
                "id": UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb2"),
                "plan_id": UUID("99999999-9999-4999-8999-999999999902"),
                "product_id": UUID("66666666-6666-4666-8666-666666666602"),
                "metric": "prompt_optimizations",
                "limit_count": 1000,
                "period": "month",
                "reset_policy": "billing_period",
                "overage_policy": "deny",
            },
            {
                "id": UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb3"),
                "plan_id": UUID("99999999-9999-4999-8999-999999999903"),
                "product_id": UUID("66666666-6666-4666-8666-666666666601"),
                "metric": "document_summary_runs",
                "limit_count": 1000,
                "period": "month",
                "reset_policy": "billing_period",
                "overage_policy": "deny",
            },
            {
                "id": UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb4"),
                "plan_id": UUID("99999999-9999-4999-8999-999999999903"),
                "product_id": UUID("66666666-6666-4666-8666-666666666602"),
                "metric": "prompt_optimizations",
                "limit_count": 1000,
                "period": "month",
                "reset_policy": "billing_period",
                "overage_policy": "deny",
            },
            {
                "id": UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb5"),
                "plan_id": UUID("99999999-9999-4999-8999-999999999904"),
                "product_id": UUID("66666666-6666-4666-8666-666666666601"),
                "metric": "document_summary_runs",
                "limit_count": 1000,
                "period": "month",
                "reset_policy": "billing_period",
                "overage_policy": "deny",
            },
            {
                "id": UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb6"),
                "plan_id": UUID("99999999-9999-4999-8999-999999999904"),
                "product_id": UUID("66666666-6666-4666-8666-666666666602"),
                "metric": "prompt_optimizations",
                "limit_count": 1000,
                "period": "month",
                "reset_policy": "billing_period",
                "overage_policy": "deny",
            },
        ],
    )



def downgrade() -> None:
    op.drop_index("ix_plan_limits_metric", table_name="plan_limits")
    op.drop_index("ix_plan_limits_plan_id", table_name="plan_limits")
    op.drop_table("plan_limits")

    op.drop_index(
        "ix_plan_price_components_source_plan_id",
        table_name="plan_price_components",
    )
    op.drop_index(
        "ix_plan_price_components_plan_position",
        table_name="plan_price_components",
    )
    op.drop_table("plan_price_components")

    op.execute("ALTER TABLE plans DROP CONSTRAINT ex_plans_active_version_overlap")
    op.drop_index("uq_plans_active_code", table_name="plans")
    op.drop_index("ix_plans_bundle_id", table_name="plans")
    op.drop_index("ix_plans_product_id", table_name="plans")
    op.drop_index("ix_plans_tenant_id", table_name="plans")
    op.drop_index("ix_plans_status", table_name="plans")
    op.drop_index("ix_plans_region_status", table_name="plans")
    op.drop_index("ix_plans_region", table_name="plans")
    op.drop_index("ix_plans_code", table_name="plans")
    op.drop_table("plans")

    op.drop_index("uq_bundle_products_active_product", table_name="bundle_products")
    op.drop_index("ix_bundle_products_product_id", table_name="bundle_products")
    op.drop_index("ix_bundle_products_bundle_status", table_name="bundle_products")
    op.drop_index("ix_bundle_products_tenant_id", table_name="bundle_products")
    op.drop_table("bundle_products")

    op.drop_index("ix_bundles_tenant_status", table_name="bundles")
    op.drop_index("ix_bundles_tenant_id", table_name="bundles")
    op.drop_index("ix_bundles_status", table_name="bundles")
    op.drop_index("ix_bundles_code", table_name="bundles")
    op.drop_table("bundles")

    op.drop_index("ix_products_tenant_status", table_name="products")
    op.drop_index("ix_products_tenant_id", table_name="products")
    op.drop_index("ix_products_status", table_name="products")
    op.drop_index("ix_products_code", table_name="products")
    op.drop_table("products")
