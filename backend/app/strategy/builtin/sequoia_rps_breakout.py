"""Sequoia-X RPS 突破: 120 日相对强度与高位突破。"""

import numpy as np

from app.backtest.matrix import (
    MarketDataMatrix,
    SignalMatrix,
    cross_section_percentile_rank,
    make_signal_matrix,
    valid_rolling_max,
    valid_shift,
)

META = {
    "id": "sequoia_rps_breakout",
    "name": "Sequoia RPS 突破",
    "description": "120 日收益横截面 RPS 不低于 90; 且收盘位于 120 日高点的 90% 以上",
    "tags": ["Sequoia-X", "RPS", "突破"],
    "asset_types": ["stock"],
    "timeframes": ["1d"],
    "basic_filter": {"enabled": False},
    "params": [
        {
            "id": "rps_threshold",
            "label": "最低 RPS",
            "type": "float",
            "default": 90.0,
            "min": 50.0,
            "max": 100.0,
            "step": 1.0,
        },
        {
            "id": "high_proximity",
            "label": "120 日高点比例",
            "type": "float",
            "default": 0.90,
            "min": 0.5,
            "max": 1.0,
            "step": 0.01,
        },
    ],
    "scoring": {},
    "order_by": "score",
    "descending": True,
    "limit": 0,
}

EXECUTION_BACKEND = "matrix_native"
ENTRY_SIGNALS = ["sequoia_rps_breakout"]
EXIT_SIGNALS = []
ALERTS = []


class SequoiaRpsBreakoutStrategy:
    def required_fields(self) -> frozenset[str]:
        return frozenset({"close", "high"})

    def required_warmup_bars(self, params: dict) -> int:
        del params
        return 120

    def compute_signals(self, market: MarketDataMatrix, params: dict) -> SignalMatrix:
        valid = np.isfinite(market.close)
        previous = valid_shift(market.close, 120, valid)
        returns = np.full(market.shape, np.nan, dtype=np.float32)
        np.divide(
            market.close,
            previous,
            out=returns,
            where=np.isfinite(previous) & (previous != 0),
        )
        returns -= np.float32(1.0)
        rps = cross_section_percentile_rank(returns) * np.float32(100.0)
        high120 = valid_rolling_max(market.high, valid & np.isfinite(market.high), 120)
        entry = (
            (rps >= float(params.get("rps_threshold", 90.0)))
            & (market.close >= high120 * float(params.get("high_proximity", 0.90)))
        )
        score = np.zeros(market.shape, dtype=np.float32)
        np.copyto(score, rps, where=entry & np.isfinite(rps))
        return make_signal_matrix(
            market.shape,
            entry=entry.astype(np.uint8),
            score=score,
            entry_signal_code=np.where(entry, 0, -1).astype(np.int16),
            entry_signal_ids=("sequoia_rps_breakout",),
        )


MATRIX_STRATEGY = SequoiaRpsBreakoutStrategy()
