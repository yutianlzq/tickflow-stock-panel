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
from app.strategy.builtin.laoniu_strategy import _break_score
from app.strategy.engine import StrategyEngine

BACKEND_ROOT = Path(__file__).resolve().parents[1]
STRATEGY_PATH = BACKEND_ROOT / "app" / "strategy" / "builtin" / "laoniu_strategy.py"


def _strategy_panel(configs: dict[str, dict] | None = None) -> pl.DataFrame:
    rows: list[dict] = []
    start = date(2026, 1, 1)
    scenario_configs = configs or {
        "000001.SZ": {"board_days": {21, 22, 23}, "break_return": -0.02, "amount": 2.5e8},
        "600000.SH": {"board_days": {22, 23}, "break_return": -0.02, "amount": 1.2e8},
        "000002.SZ": {"board_days": {22, 23}, "break_return": -0.08, "amount": 2.5e8},
        "600001.SH": {"board_days": {22, 23}, "break_return": -0.02, "amount": 0.8e8},
    }
    for symbol, config in scenario_configs.items():
        closes = config.get("closes")
        if closes is None:
            close = 10.0
            closes = []
            board_gain = float(config.get("board_gain", 0.10))
            for offset in range(25):
                if offset in config["board_days"]:
                    close *= 1.0 + board_gain
                elif offset == 24:
                    close *= 1.0 + float(config["break_return"])
                else:
                    close *= 1.01
                closes.append(close)

        for offset, close in enumerate(closes):
            shadow_ratio = float(config.get("lower_shadow_ratio", 0.25))
            if offset == 24:
                open_ = close
                high = close + (1.0 - shadow_ratio)
                low = close - shadow_ratio
            else:
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
                "amount": float(config.get("amount", 3e8)),
                "total_shares": 500_000_000.0,
                "signal_limit_up": offset in config["board_days"],
                "signal_limit_down": False,
            })
    return pl.DataFrame(rows)


def _compute(configs: dict[str, dict], params: dict | None = None):
    strategy = StrategyEngine._load_file(STRATEGY_PATH)
    market = build_market_data_matrix(
        _strategy_panel(configs),
        field_columns={"amount", "total_shares"},
    )
    resolved = StrategyEngine.resolve_params(strategy, params)
    return market, strategy.matrix_strategy.compute_signals(market, resolved)


def test_laoniu_strategy_metadata_and_backend():
    strategy = StrategyEngine._load_file(STRATEGY_PATH)
    params = {item["id"]: item for item in strategy.meta["params"]}

    assert strategy.meta["id"] == "laoniu_strategy"
    assert strategy.meta["name"] == "牢牛战法"
    assert strategy.execution_backend == "matrix_native"
    assert strategy.meta["asset_types"] == ["stock"]
    assert strategy.basic_filter["amount_min"] == 1e8
    assert strategy.matrix_strategy.required_warmup_bars({}) == 20
    assert params["max_break_drop"]["default"] == -0.075
    assert params["max_below_ma5"]["default"] == -0.03
    assert params["max_lower_shadow"]["default"] == 0.45


def test_laoniu_strategy_selects_first_break_after_exact_two_or_three_boards():
    market, signals = _compute({
        "000001.SZ": {"board_days": {21, 22, 23}, "break_return": -0.02},
        "600000.SH": {"board_days": {22, 23}, "break_return": -0.02},
        "000002.SZ": {"board_days": {22, 23}, "break_return": -0.08},
    })
    latest = signals.entry[-1]
    symbol_ids = {symbol: index for index, symbol in enumerate(market.symbols)}

    assert latest[symbol_ids["000001.SZ"]] == 1
    assert latest[symbol_ids["600000.SH"]] == 1
    assert latest[symbol_ids["000002.SZ"]] == 0
    assert signals.score[-1, symbol_ids["000001.SZ"]] > signals.score[-1, symbol_ids["600000.SH"]]
    assert signals.entry[:-1].sum() == 0


def test_strong_break_outranks_negative_break():
    market, signals = _compute({
        "000001.SZ": {"board_days": {22, 23}, "break_return": 0.05},
        "600000.SH": {"board_days": {22, 23}, "break_return": -0.05},
    })
    symbol_ids = {symbol: index for index, symbol in enumerate(market.symbols)}

    assert signals.entry[-1, symbol_ids["000001.SZ"]] == 1
    assert signals.entry[-1, symbol_ids["600000.SH"]] == 1
    assert signals.score[-1, symbol_ids["000001.SZ"]] > signals.score[-1, symbol_ids["600000.SH"]]


def test_full_bull_alignment_is_not_required():
    closes = [20.0] * 15 + [10.0] * 7 + [11.0, 12.1, 12.0]
    market, signals = _compute({
        "000001.SZ": {"board_days": {22, 23}, "closes": closes},
    })

    assert np.mean(closes[-5:]) > np.mean(closes[-10:])
    assert np.mean(closes[-10:]) < np.mean(closes[-20:])
    assert signals.entry[-1, 0] == 1
    assert signals.score[-1, 0] > 0
    assert market.symbols == ("000001.SZ",)


def test_break_below_ma5_threshold_is_rejected():
    closes = [14.0] * 20 + [20.0, 12.0, 13.2, 14.52, 13.45]
    _, signals = _compute({
        "000001.SZ": {"board_days": {22, 23}, "closes": closes},
    })

    assert closes[-1] < np.mean(closes[-5:]) * 0.97
    assert np.mean(closes[-5:]) >= np.mean(closes[-10:]) * 0.97
    assert signals.entry[-1, 0] == 0


def test_exact_four_board_is_not_laoniu():
    _, signals = _compute({
        "000001.SZ": {"board_days": {20, 21, 22, 23}, "break_return": -0.02},
    })

    assert signals.entry[-1, 0] == 0


def test_growth_board_limit_up_supported():
    _, signals = _compute({
        "300001.SZ": {
            "board_days": {22, 23},
            "board_gain": 0.20,
            "break_return": -0.02,
        },
    })

    assert signals.entry[-1, 0] == 1


def test_break_return_boundaries_are_ranked_and_filtered():
    returns = [0.05, 0.03, 0.0, -0.03, -0.05, -0.075, -0.08]
    configs = {
        f"00000{index + 1}.SZ": {
            "board_days": {22, 23},
            "closes": [10.0] * 20 + [10.0, 12.0, 14.0, 16.0, 16.0 * (1.0 + value)],
        }
        for index, value in enumerate(returns)
    }
    market, signals = _compute(configs)
    symbol_ids = {symbol: index for index, symbol in enumerate(market.symbols)}
    entries = [signals.entry[-1, symbol_ids[symbol]] for symbol in configs]

    assert entries[:6] == [1, 1, 1, 1, 1, 1]
    assert entries[6] == 0
    np.testing.assert_array_equal(
        _break_score(np.array(returns, dtype=np.float32)),
        np.array([30.0, 28.0, 25.0, 19.0, 12.0, 5.0, 5.0]),
    )


def test_laoniu_threshold_params_override_default_filters():
    below_ma5_closes = [15.0] * 20 + [16.0, 16.0, 14.5, 16.0, 15.2]
    configs = {
        "000001.SZ": {"board_days": {22, 23}, "break_return": -0.06},
        "000002.SZ": {"board_days": {22, 23}, "closes": below_ma5_closes},
        "000003.SZ": {
            "board_days": {22, 23},
            "break_return": -0.02,
            "lower_shadow_ratio": 0.40,
        },
    }
    market, default_signals = _compute(configs)
    symbol_ids = {symbol: index for index, symbol in enumerate(market.symbols)}

    assert default_signals.entry[-1].tolist() == [1, 1, 1]

    _, strict_drop = _compute(configs, {"max_break_drop": -0.05})
    _, strict_ma5 = _compute(configs, {"max_below_ma5": 0.0})
    _, strict_shadow = _compute(configs, {"max_lower_shadow": 0.35})

    assert strict_drop.entry[-1, symbol_ids["000001.SZ"]] == 0
    assert strict_ma5.entry[-1, symbol_ids["000002.SZ"]] == 0
    assert strict_shadow.entry[-1, symbol_ids["000003.SZ"]] == 0


def test_laoniu_strategy_uses_framework_basic_filter_for_liquidity():
    strategy = StrategyEngine._load_file(STRATEGY_PATH)
    market = build_market_data_matrix(
        _strategy_panel(),
        field_columns={"amount", "total_shares"},
    )

    signals = MatrixStrategyPipeline().run(
        strategy.matrix_strategy,
        market,
        StrategyEngine.resolve_params(strategy),
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
