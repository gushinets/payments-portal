"""Narrow local 043 test permission; never production/public-sale authority."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from app.core.settings import AppEnv, Settings
from app.domains.purchases.contracts import PurchaseRefused


STAND_ORIGIN = "https://043.lbxbilling.ru"


@dataclass(frozen=True)
class Stand043Permission:
    account_id: str
    user_ids: tuple[UUID, ...]
    financial_approval_reference: str

    @classmethod
    def configured(cls, configuration: Settings) -> Stand043Permission:
        if (
            configuration.app_env != AppEnv.DEVELOPMENT
            or not configuration.lbx043_enabled
            or configuration.lbx_base_url != STAND_ORIGIN
            or not configuration.mapping_account_id
            or configuration.lbx_external_billing_account_id != configuration.mapping_account_id
            or configuration.lbx_seller_organization_id != 21
            or not configuration.lbx043_test_user_ids
            or not configuration.lbx_server_username.get_secret_value()
            or not configuration.lbx_server_password.get_secret_value()
            or len(configuration.lbx_widget_signing_secret.get_secret_value().encode()) < 32
            or configuration.purchase_stand_profile_file is None
            or configuration.purchase_simulated_profile_file is not None
        ):
            raise PurchaseRefused("purchase_not_enabled", 503)
        return cls(
            configuration.mapping_account_id,
            configuration.lbx043_test_user_ids,
            configuration.lbx043_financial_approval_reference.strip(),
        )

    def require_user(self, user_id: UUID) -> None:
        if user_id not in self.user_ids:
            raise PurchaseRefused("purchase_ineligible", 403)

    def require_financial_approval(self) -> None:
        if not self.financial_approval_reference:
            raise PurchaseRefused("purchase_financial_approval_required", 409)
