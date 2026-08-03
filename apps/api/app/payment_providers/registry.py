from __future__ import annotations

from app.payment_providers.contracts import PaymentProviderAdapter


class PaymentProviderRegistry:
    def __init__(self) -> None:
        self._adapters: dict[str, PaymentProviderAdapter] = {}

    def register(self, adapter: PaymentProviderAdapter) -> None:
        self._adapters[adapter.provider_code] = adapter

    def get(self, provider_code: str) -> PaymentProviderAdapter:
        try:
            return self._adapters[provider_code]
        except KeyError as exc:
            raise LookupError(f"payment_provider_not_registered:{provider_code}") from exc

    def sole_adapter(self) -> PaymentProviderAdapter | None:
        if len(self._adapters) != 1:
            return None
        return next(iter(self._adapters.values()))


payment_provider_registry = PaymentProviderRegistry()


def get_payment_provider_registry() -> PaymentProviderRegistry:
    return payment_provider_registry
