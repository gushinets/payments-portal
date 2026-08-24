from __future__ import annotations

from fastapi import Request

from app.payment_providers.adapter import PaymentProviderAdapter


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


def get_payment_provider_registry(request: Request) -> PaymentProviderRegistry:
    try:
        return request.app.state.payment_provider_registry
    except AttributeError as exc:
        raise RuntimeError("Payment provider registry is not configured for this app") from exc
