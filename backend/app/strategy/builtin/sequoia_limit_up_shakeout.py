"""Sequoia-X 涨停洗盘: 涨停后放量收阴但不破支撑。"""

import numpy as np

from app.backtest.matrix import MarketDataMatrix, SignalMatrix, make_signal_matrix, valid_shift

META = {
    "id": "sequoia_limit_up_shakeout",
    "name": "Sequoia 涨停洗盘",
    "description": "前一交易日真实涨停; 次日放量收阴且最低价不破昨收",
    "tags": ["Sequoia-X", "涨停", "洗盘"],
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
ENTRY_SIGNALS = ["sequoia_limit_up_shakeout"]
EXIT_SIGNALS = []
ALERTS = []


class SequoiaLimitUpShakeoutStrategy:
    def required_fields(self) -> frozenset[str]:
        return frozenset({"open", "low", "close", "volume", "raw_close", "raw_high"})

    def required_warmup_bars(self, params: dict) -> int:
        del params
        return 3

    def compute_signals(self, market: MarketDataMatrix, params: dict) -> SignalMatrix:
        del params
        valid = np.isfinite(market.close)
        previous_limit_up = valid_shift(
            market.limit_up_locked.astype(np.float32),
            1,
            valid,
        )
        previous_close = valid_shift(market.close, 1, valid)
        previous_volume = valid_shift(market.volume, 1, valid & np.isfinite(market.volume))
        entry = (
            (previous_limit_up == 1)
            & (market.close < market.open)
            & (market.volume > previous_volume * np.float32(2.0))
            & (market.low >= previous_close)
        )
        return make_signal_matrix(
            market.shape,
            entry=entry.astype(np.uint8),
            entry_signal_code=np.where(entry, 0, -1).astype(np.int16),
            entry_signal_ids=("sequoia_limit_up_shakeout",),
        )


MATRIX_STRATEGY = SequoiaLimitUpShakeoutStrategy()
