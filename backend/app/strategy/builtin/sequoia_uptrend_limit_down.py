"""Sequoia-X 上升趋势跌停: 趋势中的放量跌停。"""

import numpy as np

from app.backtest.matrix import (
    MarketDataMatrix,
    SignalMatrix,
    make_signal_matrix,
    valid_rolling_mean,
    valid_shift,
)

META = {
    "id": "sequoia_uptrend_limit_down",
    "name": "Sequoia 趋势跌停",
    "description": "昨日 MA20 高于 MA60; 今日真实跌停且成交量大于含当日 20 日均量的 2 倍",
    "tags": ["Sequoia-X", "趋势", "跌停"],
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
ENTRY_SIGNALS = ["sequoia_uptrend_limit_down"]
EXIT_SIGNALS = []
ALERTS = []


class SequoiaUptrendLimitDownStrategy:
    def required_fields(self) -> frozenset[str]:
        return frozenset({"close", "volume", "raw_close", "raw_high"})

    def required_warmup_bars(self, params: dict) -> int:
        del params
        return 61

    def compute_signals(self, market: MarketDataMatrix, params: dict) -> SignalMatrix:
        del params
        valid = np.isfinite(market.close)
        ma20 = valid_rolling_mean(market.close, valid, 20)
        ma60 = valid_rolling_mean(market.close, valid, 60)
        previous_ma20 = valid_shift(ma20, 1)
        previous_ma60 = valid_shift(ma60, 1)
        vol_ma20 = valid_rolling_mean(
            market.volume,
            valid & np.isfinite(market.volume),
            20,
        )
        entry = (
            (previous_ma20 > previous_ma60)
            & market.limit_down_locked.astype(bool)
            & (market.volume > vol_ma20 * np.float32(2.0))
        )
        return make_signal_matrix(
            market.shape,
            entry=entry.astype(np.uint8),
            entry_signal_code=np.where(entry, 0, -1).astype(np.int16),
            entry_signal_ids=("sequoia_uptrend_limit_down",),
        )


MATRIX_STRATEGY = SequoiaUptrendLimitDownStrategy()
