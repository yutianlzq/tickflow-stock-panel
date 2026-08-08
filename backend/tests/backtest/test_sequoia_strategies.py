from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import numpy as np
import polars as pl

from app.backtest.matrix import (
    build_market_data_matrix,
    cross_section_percentile_rank,
)
from app.indicators.pipeline import compute_limit_signals
from app.strategy.engine import StrategyDataContext, StrategyEngine

REPO_ROOT = Path(__file__).resolve().parents[3]
BUILTIN_DIR = REPO_ROOT / "backend" / "app" / "strategy" / "builtin"


def _load_strategy(filename: str):
    return StrategyEngine._load_file(BUILTIN_DIR / filename)


def _daily_rows(
    symbol: str,
    closes: list[float],
    *,
    volumes: list[float] | None = None,
    amounts: list[float] | None = None,
    opens: list[float] | None = None,
    highs: list[float] | None = None,
    lows: list[float] | None = None,
) -> list[dict]:
    start = date(2026, 1, 1)
    size = len(closes)
    volumes = volumes or [100.0] * size
    amounts = amounts or [close * volume * 100 for close, volume in zip(closes, volumes, strict=True)]
    opens = opens or closes
    highs = highs or [close + 0.1 for close in closes]
    lows = lows or [close - 0.1 for close in closes]
    return [
        {
            "symbol": symbol,
            "name": symbol,
            "date": start + timedelta(days=index),
            "open": opens[index],
            "high": highs[index],
            "low": lows[index],
            "close": closes[index],
            "raw_close": closes[index],
            "raw_high": highs[index],
            "raw_low": lows[index],
            "volume": volumes[index],
            "amount": amounts[index],
            "float_shares": 100_000_000.0,
        }
        for index in range(size)
    ]


def _with_limit_signals(rows: list[dict]) -> pl.DataFrame:
    panel = pl.DataFrame(rows)
    instruments = panel.select("symbol", "name", "float_shares").unique(subset=["symbol"])
    return compute_limit_signals(
        panel,
        instruments,
        needed={"signal_limit_up", "signal_limit_down"},
    )


def test_cross_section_percentile_rank_matches_average_tie_ranks():
    values = np.array([
        [1.0, 2.0, 2.0, 4.0, np.nan],
        [3.0, 3.0, 1.0, np.nan, np.nan],
    ], dtype=np.float32)

    ranks = cross_section_percentile_rank(values)

    np.testing.assert_allclose(
        ranks[0, :4],
        np.array([0.25, 0.625, 0.625, 1.0], dtype=np.float32),
    )
    np.testing.assert_allclose(
        ranks[1, :3],
        np.array([5 / 6, 5 / 6, 1 / 3], dtype=np.float32),
    )
    assert np.isnan(ranks[0, 4])
    assert np.isnan(ranks[1, 3:]).all()


def test_sequoia_ma_volume_requires_golden_cross_and_20_day_volume_surge():
    base = list(np.linspace(20.0, 10.0, 20))
    rows = []
    rows.extend(_daily_rows("000001.SZ", [*base, 50.0], volumes=[100.0] * 20 + [1000.0]))
    rows.extend(_daily_rows("000002.SZ", [*base, 50.0], volumes=[100.0] * 20 + [150.0]))
    market = build_market_data_matrix(pl.DataFrame(rows))
    strategy = _load_strategy("sequoia_ma_volume.py").matrix_strategy

    signals = strategy.compute_signals(market, {})

    assert signals.entry[-1].tolist() == [1, 0]


def test_sequoia_turtle_uses_prior_20_day_high_and_market_cap_score():
    rows = []
    for symbol, bullish in (("000001.SZ", True), ("000002.SZ", False)):
        closes = [10.0] * 20 + [11.0 if bullish else 10.8]
        opens = [10.0] * 20 + [10.5 if bullish else 11.0]
        highs = [10.2] * 20 + [11.2]
        amounts = [10_000_000.0] * 20 + [120_000_000.0]
        rows.extend(_daily_rows(symbol, closes, opens=opens, highs=highs, amounts=amounts))
    market = build_market_data_matrix(
        pl.DataFrame(rows),
        field_columns={"amount", "raw_close", "float_shares"},
    )
    strategy = _load_strategy("sequoia_turtle_trade.py").matrix_strategy

    signals = strategy.compute_signals(market, {})

    assert signals.entry[-1].tolist() == [1, 0]
    assert signals.score[-1, 0] == 11.0 * 100_000_000.0


def test_sequoia_high_tight_flag_matches_momentum_contraction_and_shrinkage():
    rows = []
    for symbol, last_volume in (("000001.SZ", 500.0), ("000002.SZ", 700.0)):
        closes = list(np.linspace(10.0, 17.0, 30)) + [16.8] * 10
        highs = [close + 0.1 for close in closes]
        lows = [close - 0.1 for close in closes]
        volumes = [1000.0] * 39 + [last_volume]
        rows.extend(_daily_rows(symbol, closes, highs=highs, lows=lows, volumes=volumes))
    market = build_market_data_matrix(pl.DataFrame(rows))
    strategy = _load_strategy("sequoia_high_tight_flag.py").matrix_strategy

    signals = strategy.compute_signals(market, {})

    assert signals.entry[-1].tolist() == [1, 0]


def test_sequoia_limit_up_shakeout_uses_exchange_limit_signal():
    rows = []
    rows.extend(_daily_rows(
        "000001.SZ",
        [10.0, 11.0, 11.2],
        opens=[10.0, 10.5, 11.5],
        highs=[10.0, 11.0, 11.6],
        lows=[10.0, 10.5, 11.0],
        volumes=[100.0, 100.0, 250.0],
    ))
    rows.extend(_daily_rows(
        "000002.SZ",
        [10.0, 11.0, 11.2],
        opens=[10.0, 10.5, 11.5],
        highs=[10.0, 11.0, 11.6],
        lows=[10.0, 10.5, 10.9],
        volumes=[100.0, 100.0, 250.0],
    ))
    panel = _with_limit_signals(rows)
    market = build_market_data_matrix(
        panel,
        field_columns={"raw_close", "raw_high", "raw_low", "signal_limit_up", "signal_limit_down"},
    )
    strategy = _load_strategy("sequoia_limit_up_shakeout.py").matrix_strategy

    signals = strategy.compute_signals(market, {})

    assert market.limit_up_locked[-2].tolist() == [1, 1]
    assert signals.entry[-1].tolist() == [1, 0]


def test_sequoia_uptrend_limit_down_requires_prior_uptrend_and_volume():
    rows = []
    rising = list(np.linspace(10.0, 20.0, 60))
    previous = rising[-1]
    limit_down = round(previous * 0.9, 2)
    rows.extend(_daily_rows(
        "000001.SZ",
        [*rising, limit_down],
        volumes=[100.0] * 60 + [5000.0],
        opens=[*rising, limit_down],
        highs=[value + 0.1 for value in rising] + [limit_down],
        lows=[value - 0.1 for value in rising] + [limit_down],
    ))
    falling = list(np.linspace(20.0, 10.0, 60))
    falling_limit = round(falling[-1] * 0.9, 2)
    rows.extend(_daily_rows(
        "000002.SZ",
        [*falling, falling_limit],
        volumes=[100.0] * 60 + [5000.0],
        opens=[*falling, falling_limit],
        highs=[value + 0.1 for value in falling] + [falling_limit],
        lows=[value - 0.1 for value in falling] + [falling_limit],
    ))
    panel = _with_limit_signals(rows)
    market = build_market_data_matrix(
        panel,
        field_columns={"raw_close", "raw_high", "raw_low", "signal_limit_up", "signal_limit_down"},
    )
    strategy = _load_strategy("sequoia_uptrend_limit_down.py").matrix_strategy

    signals = strategy.compute_signals(market, {})

    assert market.limit_down_locked[-1].tolist() == [1, 1]
    assert signals.entry[-1].tolist() == [1, 0]


def _rps_panel() -> pl.DataFrame:
    rows: list[dict] = []
    for asset_id in range(10):
        symbol = f"{asset_id + 1:06d}.SZ"
        start_price = 10.0
        end_price = 10.0 + asset_id
        closes = list(np.linspace(start_price, end_price, 121))
        rows.extend(_daily_rows(symbol, closes))
    return pl.DataFrame(rows)


def test_sequoia_rps_breakout_ranks_full_market_before_pool_filter():
    panel = _rps_panel()
    market = build_market_data_matrix(panel)
    engine = StrategyEngine(strategy_dirs=[BUILTIN_DIR])
    as_of = panel["date"].max()
    low_symbol = "000001.SZ"
    high_symbol = "000010.SZ"

    low_only = engine.run(
        "sequoia_rps_breakout",
        StrategyDataContext(
            asset_type="stock",
            timeframe="1d",
            as_of=as_of,
            current=panel.filter(pl.col("date") == as_of),
            history=panel,
            market=market,
        ),
        pool=[low_symbol],
    )
    high_only = engine.run(
        "sequoia_rps_breakout",
        StrategyDataContext(
            asset_type="stock",
            timeframe="1d",
            as_of=as_of,
            current=panel.filter(pl.col("date") == as_of),
            history=panel,
            market=market,
        ),
        pool=[high_symbol],
    )

    assert low_only.total == 0
    assert [row["symbol"] for row in high_only.rows] == [high_symbol]
    assert high_only.scores[high_symbol] == 100.0
