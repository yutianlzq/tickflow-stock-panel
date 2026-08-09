from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import numpy as np
import polars as pl

from app.backtest.matrix import (
    MatrixPipelineConfig,
    MatrixStrategyPipeline,
    build_market_data_matrix,
)
from app.strategy.engine import StrategyEngine

BACKEND_ROOT = Path(__file__).resolve().parents[1]
STRATEGY_PATH = BACKEND_ROOT / "app" / "strategy" / "builtin" / "laoniu_strategy.py"


def _strategy_panel() -> pl.DataFrame:
    rows: list[dict] = []
    start = date(2026, 1, 1)
    configs = {
        "000001.SZ": {"board_days": {21, 22, 23}, "break_return": -0.02, "amount": 2.5e8},
        "600000.SH": {"board_days": {22, 23}, "break_return": -0.02, "amount": 1.2e8},
        "000002.SZ": {"board_days": {22, 23}, "break_return": -0.08, "amount": 2.5e8},
        "600001.SH": {"board_days": {22, 23}, "break_return": -0.02, "amount": 0.2e8},
    }
    for symbol, config in configs.items():
        close = 10.0
        for offset in range(25):
            previous_close = close
            if offset in config["board_days"]:
                close *= 1.10
            elif offset == 24:
                close *= 1.0 + config["break_return"]
            else:
                close *= 1.01
            open_ = close * 0.99
            high = close * 1.02
            low = close * 0.98
            rows.append({
                "symbol": symbol,
                "name": symbol,
                "date": start + timedelta(days=offset),
                "open": open_,
                "high": high,
                "low": low,
                "close": close,
                "volume": 1_000_000.0,
                "amount": config["amount"],
                "total_shares": 500_000_000.0,
                "signal_limit_up": offset in config["board_days"],
                "signal_limit_down": False,
                "previous_close": previous_close,
            })
    return pl.DataFrame(rows).drop("previous_close")


def test_laoniu_strategy_metadata_and_backend():
    strategy = StrategyEngine._load_file(STRATEGY_PATH)

    assert strategy.meta["id"] == "laoniu_strategy"
    assert strategy.meta["name"] == "牢牛战法"
    assert strategy.execution_backend == "matrix_native"
    assert strategy.meta["asset_types"] == ["stock"]
    assert strategy.matrix_strategy.required_warmup_bars({}) == 20


def test_laoniu_strategy_selects_first_break_after_exact_two_or_three_boards():
    strategy = StrategyEngine._load_file(STRATEGY_PATH)
    market = build_market_data_matrix(
        _strategy_panel(),
        field_columns={"amount", "total_shares"},
    )

    signals = strategy.matrix_strategy.compute_signals(market, {})
    latest = signals.entry[-1]
    symbol_ids = {symbol: index for index, symbol in enumerate(market.symbols)}

    assert latest[symbol_ids["000001.SZ"]] == 1
    assert latest[symbol_ids["600000.SH"]] == 1
    assert latest[symbol_ids["000002.SZ"]] == 0
    assert signals.score[-1, symbol_ids["000001.SZ"]] > signals.score[-1, symbol_ids["600000.SH"]]
    assert signals.entry[:-1].sum() == 0


def test_laoniu_strategy_uses_framework_basic_filter_for_liquidity():
    strategy = StrategyEngine._load_file(STRATEGY_PATH)
    market = build_market_data_matrix(
        _strategy_panel(),
        field_columns={"amount", "total_shares"},
    )

    signals = MatrixStrategyPipeline().run(
        strategy.matrix_strategy,
        market,
        {},
        MatrixPipelineConfig(
            basic_filter=strategy.basic_filter,
            scoring=strategy.meta["scoring"],
            order_by=strategy.meta["order_by"],
            descending=strategy.meta["descending"],
        ),
    )
    symbol_ids = {symbol: index for index, symbol in enumerate(market.symbols)}

    assert signals.entry[-1, symbol_ids["600001.SH"]] == 0
    assert np.count_nonzero(signals.entry[-1]) == 2
