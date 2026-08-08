"""Sequoia-X AkShare 企业事件数据。"""
from __future__ import annotations

import math
from datetime import date, timedelta
from typing import Any

import pandas as pd

from app.plugins.sequoia_x import bridge

_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "code": ("股票代码", "代码", "证券代码"),
    "name": ("股票简称", "名称", "证券简称"),
    "method": ("发行方式", "发行类型", "增发方式"),
    "date": ("发行日期", "增发发行日期", "增发日期"),
    "price": ("发行价格", "增发价格", "实际发行价格"),
    "quantity": ("发行数量", "实际发行数量", "增发数量"),
    "amount": ("募集资金", "实际募集资金", "募集资金总额"),
}
_REQUIRED_FIELDS = ("code", "method", "date")


def _resolve_columns(columns: list[str]) -> dict[str, str | None]:
    available = {str(column): str(column) for column in columns}
    resolved: dict[str, str | None] = {}
    for target, aliases in _FIELD_ALIASES.items():
        resolved[target] = next((available[alias] for alias in aliases if alias in available), None)
    missing = [target for target in _REQUIRED_FIELDS if resolved[target] is None]
    if missing:
        labels = ["/".join(_FIELD_ALIASES[target]) for target in missing]
        raise ValueError(f"AkShare 定增数据缺少必要字段: {', '.join(labels)}")
    return resolved


def _symbol_from_code(raw: Any) -> tuple[str, str] | None:
    digits = "".join(character for character in str(raw or "") if character.isdigit())
    if len(digits) < 6:
        return None
    code = digits[-6:]
    if code.startswith(("4", "8")):
        exchange = "BJ"
    elif code.startswith("6"):
        exchange = "SH"
    else:
        exchange = "SZ"
    return f"{code}.{exchange}", code


def _text(value: Any) -> str:
    if value is None or (isinstance(value, float) and not math.isfinite(value)):
        return ""
    text = str(value).strip()
    return "" if text.casefold() in {"nan", "none", "null"} else text


def _number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def fetch_private_placements(
    *,
    today: date | None = None,
    lookback_days: int = 7,
) -> list[dict]:
    """拉取近期定向增发事件, 返回扩展数据标准行。"""
    if lookback_days < 0:
        raise ValueError("lookback_days must be non-negative")
    akshare = bridge.load_akshare()
    frame = akshare.stock_qbzf_em()
    if frame is None or frame.empty:
        return []

    columns = _resolve_columns([str(column) for column in frame.columns])
    working = frame.copy()
    date_column = columns["date"]
    assert date_column is not None
    working["_event_date"] = pd.to_datetime(working[date_column], errors="coerce")
    working = working.dropna(subset=["_event_date"])

    method_column = columns["method"]
    assert method_column is not None
    working = working[working[method_column].astype(str).str.strip() == "定向增发"]

    current = today or date.today()
    cutoff = current - timedelta(days=lookback_days)
    working = working[
        (working["_event_date"].dt.date >= cutoff)
        & (working["_event_date"].dt.date <= current)
    ].sort_values("_event_date", ascending=False)

    code_column = columns["code"]
    assert code_column is not None
    seen: set[str] = set()
    rows: list[dict] = []
    for raw in working.to_dict(orient="records"):
        normalized = _symbol_from_code(raw.get(code_column))
        if normalized is None:
            continue
        symbol, code = normalized
        if symbol in seen:
            continue
        seen.add(symbol)
        event_date = raw["_event_date"].date().isoformat()
        rows.append({
            "symbol": symbol,
            "code": code,
            "股票简称": _text(raw.get(columns["name"])) if columns["name"] else "",
            "发行方式": "定向增发",
            "发行日期": event_date,
            "发行价格": _number(raw.get(columns["price"])) if columns["price"] else None,
            "发行数量": _number(raw.get(columns["quantity"])) if columns["quantity"] else None,
            "募集资金": _number(raw.get(columns["amount"])) if columns["amount"] else None,
        })
    return rows
