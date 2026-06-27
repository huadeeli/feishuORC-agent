from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any


FEE_FORM_ACTION = "orc_fee_form_calculate"
SERVICE_FEE_FIELD = "service_fee_per_ton"
BROKER_FEE_FIELD = "broker_fee_per_ton"

METADATA_LABELS = {
    "supplier": "供应商",
    "date": "日期",
    "plate": "车牌",
}
METADATA_ALIASES = {
    "supplier": ("供应商", "供应商名", "供货商", "供货单位", "供应单位", "发货单位", "发货单"),
    "date": ("送货日期", "发货日期", "供货日期", "供货日", "下单时间", "到场时间", "日期"),
    "plate": ("车牌号", "车牌", "车号", "车辆号"),
}
SETTLEMENT_AMOUNT_ALIASES = ("结算金额", "结算金")
PLATE_RE = re.compile(r"[京津沪渝冀豫云辽黑湘皖鲁新苏浙赣鄂桂甘晋蒙陕吉闽贵粤青藏川宁琼][A-Z][A-Z0-9]{5,7}")
MONEY_RE = re.compile(r"-?\d+(?:,\d{3})*(?:\.\d+)?")


def parse_message_content(content: Any) -> dict[str, Any]:
    if isinstance(content, dict):
        return content
    if not content:
        return {}
    try:
        parsed = json.loads(str(content))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def format_recognition_reply(result: dict[str, Any]) -> str:
    fields = {item.get("label", ""): item.get("value", "") for item in result.get("fields", [])}
    metadata = extract_display_metadata(result)
    calc = result.get("calculation", {}).get("results", {})
    factory_check = build_factory_amount_check(result, calc)
    lines = [
        "识别完成",
        f"供应商: {metadata.get('supplier', '')}",
        f"日期: {metadata.get('date', '')}",
        f"车牌: {metadata.get('plate', '')}",
        f"毛重: {fields.get('毛重', '')}",
        f"皮重: {fields.get('皮重', '')}",
        f"单价: {fields.get('单价', '')}",
        f"结算重量: {fields.get('结算重量', '')}",
        f"税费: {fields.get('税费', '')}",
        f"司磅重量: {calc.get('scale_weight', '')}",
        f"收厂钱: {calc.get('factory_amount', '')}",
        f"收厂钱验证: {factory_check['text']}" if factory_check else "",
        f"转客户钱: {calc.get('customer_amount', '')}",
    ]
    lines = [line for line in lines if line]
    warnings = [str(item) for item in result.get("warnings", []) if item]
    if warnings:
        lines.append("提醒: " + "；".join(warnings))
    return "\n".join(lines)


def build_recognition_card(result: dict[str, Any]) -> dict[str, Any]:
    fields = {str(item.get("label", "")): str(item.get("value", "")) for item in result.get("fields", [])}
    calculation = result.get("calculation", {})
    inputs = calculation.get("inputs", {}) if isinstance(calculation, dict) else {}
    calc = calculation.get("results", {}) if isinstance(calculation, dict) else {}
    return _result_card(
        title="废纸ORC识别完成",
        subtitle="图片识别结果",
        metadata=extract_display_metadata(result),
        factory_check=build_factory_amount_check(result, calc),
        inputs={
            "毛重": fields.get("毛重", ""),
            "皮重": fields.get("皮重", ""),
            "单价": fields.get("单价", ""),
            "结算重量": fields.get("结算重量", ""),
            "税费": fields.get("税费", ""),
            "手续费": _mapping_value(inputs, "service_fee_per_ton"),
            "中介费": _mapping_value(inputs, "broker_fee_per_ton"),
        },
        results=calc if isinstance(calc, dict) else {},
        warnings=result.get("warnings", []),
    )


def build_fee_input_card(
    *,
    session_id: str,
    defaults: dict[str, Any] | None = None,
    note_text: str = "",
) -> dict[str, Any]:
    defaults = defaults or {}
    service_fee = _mapping_value(defaults, SERVICE_FEE_FIELD)
    broker_fee = _mapping_value(defaults, BROKER_FEE_FIELD)
    elements: list[dict[str, Any]] = [
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": (
                    "**图片已收到**\n"
                    "请填写手续费/吨和中介费/吨，然后点击 **识别并计算**。"
                ),
            },
        },
        {
            "tag": "form",
            "name": "orc_fee_form",
            "elements": [
                {
                    "tag": "input",
                    "name": SERVICE_FEE_FIELD,
                    "label": {"tag": "plain_text", "content": "手续费/吨"},
                    "label_position": "top",
                    "default_value": service_fee,
                    "placeholder": {"tag": "plain_text", "content": "例如 15"},
                },
                {
                    "tag": "input",
                    "name": BROKER_FEE_FIELD,
                    "label": {"tag": "plain_text", "content": "中介费/吨"},
                    "label_position": "top",
                    "default_value": broker_fee,
                    "placeholder": {"tag": "plain_text", "content": "例如 3"},
                },
                {
                    "tag": "button",
                    "name": "orc_fee_submit",
                    "action_type": "form_submit",
                    "type": "primary",
                    "text": {"tag": "plain_text", "content": "识别并计算"},
                    "value": {"action": FEE_FORM_ACTION, "session_id": session_id},
                },
            ],
        },
    ]
    if note_text.strip():
        elements.append(
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": f"<font color='grey'>随图文字：{note_text.strip()}</font>",
                },
            }
        )
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "template": "blue",
            "title": {"tag": "plain_text", "content": "废纸ORC待计算"},
        },
        "elements": elements,
    }


def build_processing_card() -> dict[str, Any]:
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "template": "blue",
            "title": {"tag": "plain_text", "content": "废纸ORC正在识别"},
        },
        "elements": [
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": "已收到费用，正在识别图片并计算结果，请稍等。",
                },
            }
        ],
    }


def build_fee_form_error_card(*, session_id: str, message: str, defaults: dict[str, Any] | None = None) -> dict[str, Any]:
    card = build_fee_input_card(session_id=session_id, defaults=defaults)
    card["header"]["template"] = "red"
    card["elements"].insert(
        0,
        {
            "tag": "div",
            "text": {"tag": "lark_md", "content": f"**输入有误**\n{message}"},
        },
    )
    return card


def format_calculation_reply(result: dict[str, Any]) -> str:
    labels = result.get("labels", {})
    inputs = result.get("inputs", {})
    calc = result.get("results", {})
    lines = [
        "文字计算完成",
        f"{labels.get('gross_weight', '毛重')}: {inputs.get('gross_weight', '')}",
        f"{labels.get('tare_weight', '皮重')}: {inputs.get('tare_weight', '')}",
        f"{labels.get('unit_price', '单价')}: {inputs.get('unit_price', '')}",
        f"{labels.get('settlement_weight', '结算重量')}: {inputs.get('settlement_weight', '')}",
        f"{labels.get('tax_fee', '税费')}: {inputs.get('tax_fee', '')}",
        f"{labels.get('scale_weight', '司磅重量')}: {calc.get('scale_weight', '')}",
        f"{labels.get('factory_amount', '收厂钱')}: {calc.get('factory_amount', '')}",
        f"{labels.get('customer_amount', '转客户钱')}: {calc.get('customer_amount', '')}",
    ]
    return "\n".join(lines)


def build_calculation_card(result: dict[str, Any]) -> dict[str, Any]:
    labels = result.get("labels", {})
    inputs = result.get("inputs", {})
    calc = result.get("results", {})
    return _result_card(
        title="废纸ORC文字计算完成",
        subtitle="文字字段计算结果",
        metadata={},
        factory_check=None,
        inputs={
            str(labels.get("gross_weight", "毛重")): _mapping_value(inputs, "gross_weight"),
            str(labels.get("tare_weight", "皮重")): _mapping_value(inputs, "tare_weight"),
            str(labels.get("unit_price", "单价")): _mapping_value(inputs, "unit_price"),
            str(labels.get("settlement_weight", "结算重量")): _mapping_value(inputs, "settlement_weight"),
            str(labels.get("tax_fee", "税费")): _mapping_value(inputs, "tax_fee"),
            str(labels.get("service_fee_per_ton", "手续费")): _mapping_value(inputs, "service_fee_per_ton"),
            str(labels.get("broker_fee_per_ton", "中介费")): _mapping_value(inputs, "broker_fee_per_ton"),
        },
        results=calc if isinstance(calc, dict) else {},
        warnings=[],
    )


def help_text() -> str:
    return "\n".join(
        [
            "我可以接收废纸结算截图，也可以接收文字字段。",
            "发图片：直接发送截图，我会识别并计算。",
            "发文字：例如 毛重45.74 皮重15.81 单价1800 结算重量29.5 税费800 手续费15",
        ]
    )


def format_error_reply(error: BaseException) -> str:
    return "识别失败，请确认图片清晰后重试。\n错误: " + str(error)


def _result_card(
    *,
    title: str,
    subtitle: str,
    metadata: dict[str, Any],
    factory_check: dict[str, str] | None,
    inputs: dict[str, Any],
    results: dict[str, Any],
    warnings: Any,
) -> dict[str, Any]:
    customer_amount = _mapping_value(results, "customer_amount")
    factory_amount = _mapping_value(results, "factory_amount")
    scale_weight = _mapping_value(results, "scale_weight")
    customer_service_fee = _mapping_value(results, "customer_service_fee")
    customer_broker_fee = _mapping_value(results, "customer_broker_fee")

    elements: list[dict[str, Any]] = [
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": (
                    f"**{subtitle}**\n"
                    f"{_red_bold('转客户钱：' + _display(customer_amount))}\n"
                    f"收厂钱：{_display(factory_amount)}　司磅重量：{_display(scale_weight)}"
                ),
            },
        },
    ]
    if _has_metadata(metadata):
        elements.extend(
            [
                {"tag": "hr"},
                {
                    "tag": "div",
                    "fields": _fields_from_pairs(
                        [
                            ("供应商", metadata.get("supplier", "")),
                            ("日期", metadata.get("date", "")),
                            ("车牌", metadata.get("plate", "")),
                        ]
                    ),
                },
            ]
        )
    elements.extend(
        [
            {"tag": "hr"},
            {
                "tag": "div",
                "fields": _fields_from_pairs(
                    [
                        ("毛重", inputs.get("毛重", "")),
                        ("皮重", inputs.get("皮重", "")),
                        ("单价", inputs.get("单价", "")),
                        ("结算重量", inputs.get("结算重量", "")),
                        ("税费", inputs.get("税费", "")),
                        ("手续费", inputs.get("手续费", ""), "blue"),
                        ("中介费", inputs.get("中介费", ""), "blue"),
                        ("客户手续费", customer_service_fee, "blue"),
                        ("客户中介费", customer_broker_fee, "blue"),
                    ]
                ),
            },
            {"tag": "hr"},
            {
                "tag": "div",
                "text": {"tag": "lark_md", "content": _calculation_process_text(inputs, results, factory_check)},
            },
        ]
    )

    warning_text = _format_warnings(warnings)
    if warning_text:
        elements.extend(
            [
                {"tag": "hr"},
                {
                    "tag": "div",
                    "text": {"tag": "lark_md", "content": f"**提醒**\n{warning_text}"},
                },
            ]
        )

    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "template": "green",
            "title": {"tag": "plain_text", "content": title},
        },
        "elements": elements,
    }


def _fields_from_pairs(pairs: list[tuple[str, Any] | tuple[str, Any, str]]) -> list[dict[str, Any]]:
    fields: list[dict[str, Any]] = []
    for item in pairs:
        label, value = item[0], item[1]
        color = item[2] if len(item) > 2 else ""
        content = f"**{label}**\n{_display(value)}"
        if color:
            content = f"<font color='{color}'>{label}\n{_display(value)}</font>"
        fields.append(
            {
                "is_short": True,
                "text": {"tag": "lark_md", "content": content},
            }
        )
    return fields


def extract_display_metadata(result: dict[str, Any]) -> dict[str, str]:
    fields = {
        str(item.get("label", "")): str(item.get("value", "")).strip()
        for item in result.get("fields", [])
        if isinstance(item, dict)
    }
    metadata = {
        "supplier": _first_field_value(fields, ("供应商", "供应商名", "供货商", "供货单位", "供应单位", "发货单位", "发货单")),
        "date": _first_field_value(fields, ("送货日期", "发货日期", "供货日期", "供货日", "下单时间", "日期")),
        "plate": _first_field_value(fields, ("车牌号", "车牌", "车号", "车辆号")),
    }
    ocr_texts = _ocr_texts(result)
    for key, aliases in METADATA_ALIASES.items():
        if not metadata[key]:
            metadata[key] = _extract_text_value(ocr_texts, aliases)
    if not metadata["plate"]:
        metadata["plate"] = _find_plate(ocr_texts)
    return metadata


def build_factory_amount_check(result: dict[str, Any], results: Any) -> dict[str, str] | None:
    if not isinstance(results, dict):
        return None
    factory_amount = _mapping_value(results, "factory_amount")
    if not factory_amount:
        return None
    image_amount = extract_image_settlement_amount(result)
    if not image_amount:
        return {"status": "fail", "text": "验证不通过，未识别到图片结算金额"}
    if _money_equal(factory_amount, image_amount):
        return {"status": "pass", "text": "验证一致", "image_amount": image_amount}
    return {
        "status": "fail",
        "text": f"验证不通过，图片结算金额={image_amount}",
        "image_amount": image_amount,
    }


def extract_image_settlement_amount(result: dict[str, Any]) -> str:
    return _extract_money_value(_ocr_texts(result), SETTLEMENT_AMOUNT_ALIASES)


def _first_field_value(fields: dict[str, str], labels: tuple[str, ...]) -> str:
    for label in labels:
        value = fields.get(label, "").strip()
        if value:
            return value
    return ""


def _ocr_texts(result: dict[str, Any]) -> list[str]:
    texts: list[str] = []
    lines = result.get("ocr_lines", [])
    if not isinstance(lines, list):
        return texts
    for line in lines:
        if isinstance(line, dict):
            text = str(line.get("text") or "").strip()
        else:
            text = str(line or "").strip()
        if text:
            texts.append(text)
    return texts


def _extract_text_value(texts: list[str], aliases: tuple[str, ...]) -> str:
    for index, text in enumerate(texts):
        compact = _compact_text(text)
        for alias in aliases:
            compact_alias = _compact_text(alias)
            if compact_alias not in compact:
                continue
            value = compact.split(compact_alias, 1)[-1]
            value = _clean_metadata_value(value)
            if value:
                return value
            for next_text in texts[index + 1:index + 3]:
                candidate = _clean_metadata_value(next_text)
                if candidate and not _looks_like_label(candidate):
                    return candidate
    return ""


def _extract_money_value(texts: list[str], aliases: tuple[str, ...]) -> str:
    for index, text in enumerate(texts):
        compact = _compact_text(text)
        if "含税" in compact:
            continue
        for alias in aliases:
            compact_alias = _compact_text(alias)
            if compact_alias not in compact:
                continue
            after_alias = compact.split(compact_alias, 1)[-1]
            match = MONEY_RE.search(after_alias)
            if match:
                return match.group(0).replace(",", "")
            for next_text in texts[index + 1:index + 3]:
                next_compact = _compact_text(next_text)
                if "含税" in next_compact or _looks_like_label(next_compact):
                    continue
                next_match = MONEY_RE.search(next_compact)
                if next_match:
                    return next_match.group(0).replace(",", "")
    return ""


def _find_plate(texts: list[str]) -> str:
    for text in texts:
        match = PLATE_RE.search(_compact_text(text).upper())
        if match:
            return match.group(0)
    return ""


def _compact_text(text: str) -> str:
    return str(text or "").replace(" ", "").replace("\t", "").replace("：", ":").replace("*", "")


def _clean_metadata_value(text: str) -> str:
    value = str(text or "").strip().strip(":：=-_.。…").strip()
    value = re.sub(r"^[.。…]+", "", value).strip()
    return value


def _looks_like_label(text: str) -> bool:
    compact = _compact_text(text)
    aliases = tuple(alias for group in METADATA_ALIASES.values() for alias in group)
    return any(_compact_text(alias) in compact for alias in aliases)


def _has_metadata(metadata: dict[str, Any]) -> bool:
    return any(str(metadata.get(key, "")).strip() for key in METADATA_LABELS)


def _calculation_process_text(
    inputs: dict[str, Any],
    results: dict[str, Any],
    factory_check: dict[str, str] | None,
) -> str:
    scale_weight = _mapping_value(results, "scale_weight")
    service_fee = _fee_value(inputs.get("手续费"))
    broker_fee = _fee_value(inputs.get("中介费"))
    unit_price = _display(inputs.get("单价"))
    settlement_weight = _display(inputs.get("结算重量"))
    tax_fee = _display(inputs.get("税费"))
    customer_service_fee = _mapping_value(results, "customer_service_fee")
    customer_broker_fee = _mapping_value(results, "customer_broker_fee")
    factory_amount = _mapping_value(results, "factory_amount")
    customer_amount = _mapping_value(results, "customer_amount")

    factory_check_text = f"（{factory_check['text']}）" if factory_check else ""
    return "\n".join(
        [
            "**计算过程**",
            _blue(f"客户手续费：{_display(scale_weight)} × {service_fee} = {_display(customer_service_fee)}"),
            _blue(f"客户中介费：{_display(scale_weight)} × {broker_fee} = {_display(customer_broker_fee)}"),
            f"收厂钱：{unit_price} × {settlement_weight} - {tax_fee} = {_display(factory_amount)}{factory_check_text}",
            _red_bold(
                f"转客户钱：{_display(factory_amount)} - {_display(customer_service_fee)} = {_display(customer_amount)}"
            ),
        ]
    )


def _format_warnings(warnings: Any) -> str:
    if not isinstance(warnings, list):
        return ""
    cleaned = [_humanize_warning(str(item)) for item in warnings if item]
    return "；".join(cleaned)


def _humanize_warning(text: str) -> str:
    return (
        text.replace("service_fee_per_ton", "手续费")
        .replace("broker_fee_per_ton", "中介费")
        .replace(": ", "：")
    )


def _mapping_value(mapping: Any, key: str) -> str:
    if isinstance(mapping, dict):
        value = mapping.get(key, "")
        return "" if value is None else str(value)
    return ""


def _display(value: Any) -> str:
    text = "" if value is None else str(value)
    return text if text else "-"


def _fee_value(value: Any) -> str:
    text = "" if value is None else str(value).strip()
    return text if text and text != "-" else "0"


def _money_equal(left: Any, right: Any) -> bool:
    try:
        left_decimal = Decimal(str(left).replace(",", "")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        right_decimal = Decimal(str(right).replace(",", "")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        return False
    return left_decimal == right_decimal


def _red_bold(text: str) -> str:
    return f"<font color='red'>**{text}**</font>"


def _blue(text: str) -> str:
    return f"<font color='blue'>{text}</font>"
