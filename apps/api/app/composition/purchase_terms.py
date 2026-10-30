"""Explicit development data boundary, independent of the Kernel mock."""

from pathlib import Path

from app.core.settings import AppEnv, Settings
from app.domains.catalog.admission import SelectedCapabilityUnavailable
from app.domains.catalog.contracts import CapabilityManifest
from app.domains.catalog.link_publication import StoredProductLink
from app.domains.catalog.product_link import CurrentOffer
from app.domains.purchases.contracts import PurchaseRefused
from app.domains.purchases.technical_terms import AcceptedTechnicalTerms, TestTermsSource, bind_test_terms

TEST_TERMS_PATH = Path(__file__).resolve().parents[4] / "config/development/paid-access-test-terms.json"


def current_technical_terms(
    configuration: Settings, manifest: CapabilityManifest, link: StoredProductLink, offer: CurrentOffer
) -> AcceptedTechnicalTerms | None:
    if not configuration.purchase_test_terms_enabled:
        return None
    if configuration.app_env == AppEnv.PRODUCTION:
        raise PurchaseRefused("purchase_technical_terms_unavailable", 503)
    try:
        source = TestTermsSource.model_validate_json(TEST_TERMS_PATH.read_text(encoding="utf-8"))
        return bind_test_terms(
            source,
            manifest,
            account_id=link.document.scope.external_billing_account_id,
            revision_id=link.mapping_revision_id,
            selection=link.document.selection,
            commercial_fingerprint=offer.fingerprint,
        )
    except (OSError, ValueError, SelectedCapabilityUnavailable):
        raise PurchaseRefused("purchase_technical_terms_unavailable", 503) from None
