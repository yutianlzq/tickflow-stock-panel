"""Sequoia-X 均线放量: MA5 上穿 MA20 且成交量放大。"""

import numpy as np

from app.backtest.matrix import (
    MarketDataMatrix,
    SignalMatrix,
    make_signal_matrix,
    valid_rolling_mean,
    valid_shift,
)

META = {
    "id": "sequoia_ma_volume",
    "name": "Sequoia 均线放量",
    "description": "MA5 上穿 MA20; 且当日成交量大于含当日 20 日均量的 1.5 倍",
    "tags": ["Sequoia-X", "均线", "放量"],
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
ENTRY_SIGNALS = ["sequoia_ma_volume"]
EXIT_SIGNALS = []
ALERTS = []


class SequoiaMaVolumeStrategy:
    def required_fields(self) -> frozenset[str]:
        return frozenset({"close", "volume"})

    def required_warmup_bars(self, params: dict) -> int:
        del params
        return 20

    def compute_signals(self, market: MarketDataMatrix, params: dict) -> SignalMatrix:
        del params
        valid = np.isfinite(market.close)
        ma5 = valid_rolling_mean(market.close, valid, 5)
        ma20 = valid_rolling_mean(market.close, valid, 20)
        vol_ma20 = valid_rolling_mean(market.volume, valid & np.isfinite(market.volume), 20)
        golden = (ma5 > ma20) & (valid_shift(ma5, 1) < valid_shift(ma20, 1))
        entry = golden & (market.volume > vol_ma20 * np.float32(1.5))
        return make_signal_matrix(
            market.shape,
            entry=entry.astype(np.uint8),
            entry_signal_code=np.where(entry, 0, -1).astype(np.int16),
            entry_signal_ids=("sequoia_ma_volume",),
        )


MATRIX_STRATEGY = SequoiaMaVolumeStrategy()
