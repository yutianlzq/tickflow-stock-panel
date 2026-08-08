"""Sequoia-X Baostock 日 K 数据源 provider。"""
from __future__ import annotations

import logging
import os
from concurrent.futures import ProcessPoolExecutor
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import polars as pl

from app.data_providers.normalizer import normalize_daily
from app.plugins.sequoia_x import bridge

logger = logging.getLogger(__name__)

_DATASETS = ("daily",)
_HISTORY_FIELDS = "date,open,high,low,close,volume,amount"
_DEFAULT_DAYS = 365
_DEFAULT_BATCH = 200
_MAX_WORKERS = 8


@dataclass
class _SequoiaXConfig:
    """供插件注册表识别能力的轻量配置。"""

    name: str = "sequoia_x"
    display_name: str = "Sequoia-X (Baostock/AkShare)"
    datasets: dict = field(default_factory=lambda: dict.fromkeys(_DATASETS))
    path: None = None
    builtin: bool = True


def _to_baostock_code(symbol: str) -> str:
    normalized = str(symbol or "").strip().upper()
    if normalized.endswith(".SH") and normalized[:6].isdigit():
        return f"sh.{normalized[:6]}"
    if normalized.endswith(".SZ") and normalized[:6].isdigit():
        return f"sz.{normalized[:6]}"
    raise ValueError(f"Sequoia-X Baostock 首版仅支持沪深 A 股: {symbol}")


def _to_app_symbol(code: str) -> str | None:
    normalized = str(code or "").strip().lower()
    if normalized.startswith("sh.") and normalized[3:].isdigit():
        return f"{normalized[3:]}.SH"
    if normalized.startswith("sz.") and normalized[3:].isdigit():
        return f"{normalized[3:]}.SZ"
    return None


def _result_rows(result) -> list[dict[str, str]]:
    fields = list(getattr(result, "fields", []) or [])
    rows: list[dict[str, str]] = []
    while result.next():
        values = result.get_row_data()
        rows.append(dict(zip(fields, values, strict=False)))
    return rows


def _fetch_daily_chunk(tasks: list[tuple[str, str, str, str]]) -> tuple[list[dict], list[str]]:
    """单个进程内复用一次 Baostock 登录, 返回标准行和失败标的。"""
    bs = bridge.load_baostock()
    rows: list[dict] = []
    failed: list[str] = []
    login = bs.login()
    if getattr(login, "error_code", "") != "0":
        with suppress(Exception):
            bs.logout()
        return rows, [task[0] for task in tasks]

    try:
        for symbol, bs_code, start_date, end_date in tasks:
            try:
                result = bs.query_history_k_data_plus(
                    bs_code,
                    _HISTORY_FIELDS,
                    start_date=start_date,
                    end_date=end_date,
                    frequency="d",
                    adjustflag="3",
                )
                if getattr(result, "error_code", "") != "0":
                    failed.append(symbol)
                    continue
                for raw in _result_rows(result):
                    try:
                        # Baostock 日线 volume 为股; 内部统一使用手。
                        volume_lots = float(raw.get("volume") or 0) / 100.0
                        close = float(raw.get("close") or "nan")
                        rows.append({
                            "symbol": symbol,
                            "date": raw.get("date"),
                            "open": float(raw.get("open") or "nan"),
                            "high": float(raw.get("high") or "nan"),
                            "low": float(raw.get("low") or "nan"),
                            "close": close,
                            "volume": volume_lots,
                            "amount": float(raw.get("amount") or 0),
                        })
                    except (TypeError, ValueError):
                        continue
            except Exception:
                failed.append(symbol)
    finally:
        with suppress(Exception):
            bs.logout()
    return rows, failed


def _fetch_daily_chunk_safe(tasks: list[tuple[str, str, str, str]]) -> tuple[list[dict], list[str]]:
    """隔离 worker 启动、依赖导入和登录异常, 保持批次级失败可见。"""
    try:
        return _fetch_daily_chunk(tasks)
    except Exception as exc:
        logger.warning("Sequoia-X 日 K 批次失败: %s", exc)
        return [], [task[0] for task in tasks]


def _chunked(values: list, size: int) -> list[list]:
    return [values[index:index + size] for index in range(0, len(values), size)]


class SequoiaXProvider:
    """Baostock 沪深 A 股不复权日 K 与标的维表。"""

    name = "sequoia_x"
    builtin = True

    def __init__(self) -> None:
        self.config = _SequoiaXConfig()

    def close(self) -> None:
        pass

    def get_daily(
        self,
        symbols: list[str],
        start_time: datetime | None,
        end_time: datetime | None,
        asset_type: str = "stock",
        on_chunk_done=None,
    ) -> pl.DataFrame:
        if asset_type != "stock" or not symbols:
            return pl.DataFrame()

        end = end_time or datetime.now()
        start = start_time or (end - timedelta(days=_DEFAULT_DAYS))
        tasks = [
            (
                str(symbol).strip().upper(),
                _to_baostock_code(symbol),
                start.strftime("%Y-%m-%d"),
                end.strftime("%Y-%m-%d"),
            )
            for symbol in symbols
        ]
        batches = _chunked(tasks, _DEFAULT_BATCH)
        workers = self._worker_count(len(batches))
        results: list[tuple[list[dict], list[str]]] = []

        if workers == 1:
            for index, batch in enumerate(batches):
                results.append(_fetch_daily_chunk_safe(batch))
                if on_chunk_done:
                    on_chunk_done(index + 1, len(batches))
        else:
            with ProcessPoolExecutor(max_workers=workers) as pool:
                for index, result in enumerate(pool.map(_fetch_daily_chunk_safe, batches)):
                    results.append(result)
                    if on_chunk_done:
                        on_chunk_done(index + 1, len(batches))

        rows = [row for batch_rows, _ in results for row in batch_rows]
        failed = [symbol for _, batch_failed in results for symbol in batch_failed]
        if failed:
            logger.warning(
                "Sequoia-X 日 K 部分失败: %d/%d 标的保持旧数据 (样例: %s)",
                len(set(failed)),
                len(symbols),
                sorted(set(failed))[:10],
            )
        if not rows:
            return pl.DataFrame()
        return normalize_daily(pl.DataFrame(rows), source=self.name)

    def get_instruments(self, asset_type: str = "stock") -> list[dict]:
        if asset_type != "stock":
            return []
        try:
            bs = bridge.load_baostock()
            login = bs.login()
        except Exception as exc:
            logger.warning("Sequoia-X Baostock 标的依赖或登录失败: %s", exc)
            return []
        if getattr(login, "error_code", "") != "0":
            logger.warning("Sequoia-X Baostock 标的登录失败: %s", getattr(login, "error_msg", ""))
            with suppress(Exception):
                bs.logout()
            return []
        try:
            result = bs.query_stock_basic(code_name="", code="")
            if getattr(result, "error_code", "") != "0":
                logger.warning("Sequoia-X Baostock 标的拉取失败: %s", getattr(result, "error_msg", ""))
                return []
            instruments: list[dict] = []
            for row in _result_rows(result):
                symbol = _to_app_symbol(row.get("code", ""))
                if not symbol or row.get("type") != "1" or row.get("status") != "1":
                    continue
                exchange = symbol.rsplit(".", 1)[1]
                instruments.append({
                    "symbol": symbol,
                    "name": row.get("code_name") or symbol,
                    "code": symbol[:6],
                    "exchange": exchange,
                    "region": "CN",
                    "type": "stock",
                    "ext": {"listing_date": row.get("ipoDate") or None},
                })
            return instruments
        except Exception as exc:
            logger.warning("Sequoia-X Baostock 标的拉取异常: %s", exc)
            return []
        finally:
            with suppress(Exception):
                bs.logout()

    def test_dataset(self, dataset: str, symbols: list[str] | None = None) -> dict:
        if dataset != "daily":
            raise ValueError(f"Sequoia-X 不支持数据集: {dataset}")
        df = self.get_daily(symbols or ["600519.SH"], None, None)
        return {
            "provider": self.name,
            "dataset": dataset,
            "rows": df.height,
            "columns": df.columns,
            "preview": df.head(5).to_dicts() if not df.is_empty() else [],
        }

    @staticmethod
    def _worker_count(batch_count: int) -> int:
        raw = os.getenv("SEQUOIA_BAOSTOCK_WORKERS", "4")
        try:
            configured = int(raw)
        except ValueError:
            configured = 4
        return max(1, min(_MAX_WORKERS, configured, batch_count))
