from __future__ import annotations

from decimal import Decimal
from typing import Any, Mapping

from .money import decimal_to_str, quantize_money, quantize_weight, to_decimal


RECOGNIZED_FIELDS = (
    "gross_weight",
    "tare_weight",
    "unit_price",
    "settlement_weight",
    "tax_fee",
)

MANUAL_FIELDS = ("service_fee_per_ton", "broker_fee_per_ton")

FIELD_LABELS = {
    "gross_weight": "毛重",
    "tare_weight": "皮重",
    "unit_price": "单价",
    "settlement_weight": "结算重量",
    "tax_fee": "税费",
    "service_fee_per_ton": "手续费",
    "broker_fee_per_ton": "中介费",
    "scale_weight": "司磅重量",
    "customer_service_fee": "客户手续费",
    "customer_broker_fee": "客户中介费",
    "factory_amount": "收厂钱",
    "customer_amount": "转客户钱",
}


def calculate(values: Mapping[str, Any]) -> dict[str, str]:
    gross_weight = to_decimal(values.get("gross_weight"))
    tare_weight = to_decimal(values.get("tare_weight"))
    unit_price = to_decimal(values.get("unit_price"))
    settlement_weight = to_decimal(values.get("settlement_weight"))
    tax_fee = to_decimal(values.get("tax_fee"))
    service_fee = to_decimal(values.get("service_fee_per_ton"))
    broker_fee = to_decimal(values.get("broker_fee_per_ton"))

    scale_weight = gross_weight - tare_weight
    customer_service_fee = scale_weight * service_fee
    customer_broker_fee = scale_weight * broker_fee
    factory_amount = unit_price * settlement_weight - tax_fee
    customer_amount = factory_amount - customer_service_fee

    return {
        "scale_weight": decimal_to_str(quantize_weight(scale_weight), places=3),
        "customer_service_fee": decimal_to_str(quantize_money(customer_service_fee), places=2),
        "customer_broker_fee": decimal_to_str(quantize_money(customer_broker_fee), places=2),
        "factory_amount": decimal_to_str(quantize_money(factory_amount), places=2),
        "customer_amount": decimal_to_str(quantize_money(customer_amount), places=2),
    }


def calculation_payload(values: Mapping[str, Any]) -> dict[str, Any]:
    results = calculate(values)
    return {
        "inputs": {
            key: str(values.get(key, ""))
            for key in (*RECOGNIZED_FIELDS, *MANUAL_FIELDS)
        },
        "results": results,
        "labels": FIELD_LABELS,
        "currency": "CNY",
        "fee_unit": "元/吨",
    }
