from __future__ import annotations

import json
from typing import Any

from app.integrations.cloudpayments.payload import get_first
from app.models import Order, OrderStatus, PaymentStatus

TERMINAL_ORDER_STATUSES = {
    OrderStatus.PAID,
    OrderStatus.CANCELED,
    OrderStatus.REFUNDED,
    OrderStatus.PARTIALLY_REFUNDED,
}
TERMINAL_PAYMENT_STATUSES = {
    PaymentStatus.SUCCEEDED,
    PaymentStatus.CANCELED,
    PaymentStatus.REFUNDED,
    PaymentStatus.PARTIALLY_REFUNDED,
}


def parse_data(payload: dict[str, Any]) -> dict[str, Any]:
    data = get_first(payload, "Data", "data")
    if isinstance(data, dict):
        return data
    if isinstance(data, str) and data:
        try:
            parsed = json.loads(data)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def safe_summary(payload: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    return {
        "invoice_id": get_first(payload, "InvoiceId", "invoiceId", "invoice_id"),
        "transaction_id": get_first(payload, "TransactionId", "transactionId", "transaction_id"),
        "account_id": get_first(payload, "AccountId", "accountId", "account_id"),
        "payment_method_type": get_first(payload, "PaymentMethod", "paymentMethod"),
        "reason_code": get_first(payload, "ReasonCode", "reasonCode"),
        "reason": get_first(payload, "Reason", "reason"),
        "data": {key: value for key, value in data.items() if key in {"product_code", "plan_code", "auto_renew"}},
    }


def terminal_order_event_error_code(order: Order) -> str:
    codes = {
        OrderStatus.CANCELED: "order_already_canceled",
        OrderStatus.REFUNDED: "order_already_refunded",
        OrderStatus.PARTIALLY_REFUNDED: "order_already_refunded",
    }
    return codes.get(order.status, "order_already_paid")
