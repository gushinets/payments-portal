"""Published technical terms, with an explicit isolated development source."""

from pathlib import Path

from app.core.settings import AppEnv, Settings
from app.domains.catalog.admission import SelectedCapabilityUnavailable
from app.domains.catalog.contracts import CapabilityManifest
from app.domains.catalog.link_publication import StoredProductLink
from app.domains.catalog.product_link import CurrentOffer
from app.domains.purchases.contracts import PurchaseRefused
from app.domains.purchases.technical_terms import (
    AcceptedTechnicalTerms,
    TestTermsSource,
    bind_test_terms,
    bind_published_terms,
)

TEST_TERMS_PATH = Path(__file__).resolve().parents[4] / "config/development/paid-access-test-terms.json"


def current_technical_terms(
    configuration: Settings, manifest: CapabilityManifest, link: StoredProductLink, offer: CurrentOffer
) -> AcceptedTechnicalTerms | None:
    if link.document.technical_offer is not None:
        try:
            return bind_published_terms(
                link.document,
                manifest,
                revision_id=link.mapping_revision_id,
                commercial_fingerprint=offer.fingerprint,
            )
        except (ValueError, SelectedCapabilityUnavailable):
            raise PurchaseRefused("purchase_technical_terms_unavailable", 503) from None
    # Legacy history remains readable/replayable, but supplies no published
    # quantity for a genuinely new production purchase.
    if configuration.app_env == AppEnv.PRODUCTION:
        raise PurchaseRefused("purchase_technical_terms_unavailable", 503)
    if not configuration.purchase_test_terms_enabled:
        return None
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
