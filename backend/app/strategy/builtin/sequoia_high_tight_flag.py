"""Sequoia-X 高窄旗形: 强动量后的高位收敛缩量。"""

import numpy as np

from app.backtest.matrix import (
    MarketDataMatrix,
    SignalMatrix,
    make_signal_matrix,
    valid_rolling_max,
    valid_rolling_mean,
    valid_rolling_min,
    valid_shift,
)

META = {
    "id": "sequoia_high_tight_flag",
    "name": "Sequoia 高窄旗形",
    "description": "40 日强动量、近 10 日高位收敛; 且当日相对前 20 日均量缩量",
    "tags": ["Sequoia-X", "旗形", "缩量"],
    "asset_types": ["stock"],
    "timeframes": ["1d"],
    "basic_filter": {"enabled": False},
    "params": [],
    "scoring": {},
    "order_by": "score",
    "descending": True,
    "limit": 0,
}

EXECUTION_BACKEND = "matrix_native"
ENTRY_SIGNALS = ["sequoia_high_tight_flag"]
EXIT_SIGNALS = []
ALERTS = []


class SequoiaHighTightFlagStrategy:
    def required_fields(self) -> frozenset[str]:
        return frozenset({"high", "low", "volume"})

    def required_warmup_bars(self, params: dict) -> int:
        del params
        return 40

    def compute_signals(self, market: MarketDataMatrix, params: dict) -> SignalMatrix:
        del params
        valid = np.isfinite(market.close)
        high40 = valid_rolling_max(market.high, valid & np.isfinite(market.high), 40)
        low40 = valid_rolling_min(market.low, valid & np.isfinite(market.low), 40)
        high10 = valid_rolling_max(market.high, valid & np.isfinite(market.high), 10)
        low10 = valid_rolling_min(market.low, valid & np.isfinite(market.low), 10)
        previous_volume = valid_shift(market.volume, 1, valid & np.isfinite(market.volume))
        prior_vol_ma20 = valid_rolling_mean(
            previous_volume,
            np.isfinite(previous_volume),
            20,
        )
        entry = (
            (low40 > 0)
            & (low10 > 0)
            & (high40 / low40 > np.float32(1.6))
            & (high10 / low10 < np.float32(1.15))
            & (low10 >= high40 * np.float32(0.8))
            & (market.volume < prior_vol_ma20 * np.float32(0.6))
        )
        return make_signal_matrix(
            market.shape,
            entry=entry.astype(np.uint8),
            entry_signal_code=np.where(entry, 0, -1).astype(np.int16),
            entry_signal_ids=("sequoia_high_tight_flag",),
        )


MATRIX_STRATEGY = SequoiaHighTightFlagStrategy()
