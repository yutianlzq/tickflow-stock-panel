"""Sequoia-X 海龟突破: 前 20 日新高、流动性和阳线确认。"""

import numpy as np

from app.backtest.matrix import (
    MarketDataMatrix,
    SignalMatrix,
    make_signal_matrix,
    valid_rolling_max,
    valid_shift,
)

META = {
    "id": "sequoia_turtle_trade",
    "name": "Sequoia 海龟突破",
    "description": "收盘突破前 20 个交易日最高价; 成交额过亿且收阳真涨",
    "tags": ["Sequoia-X", "海龟", "突破"],
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
ENTRY_SIGNALS = ["sequoia_turtle_breakout"]
EXIT_SIGNALS = []
ALERTS = []


class SequoiaTurtleTradeStrategy:
    def required_fields(self) -> frozenset[str]:
        return frozenset({"open", "high", "close", "raw_close", "amount", "float_shares"})

    def required_warmup_bars(self, params: dict) -> int:
        del params
        return 21

    def compute_signals(self, market: MarketDataMatrix, params: dict) -> SignalMatrix:
        del params
        valid = np.isfinite(market.close)
        prior_high = valid_rolling_max(
            valid_shift(market.high, 1, valid),
            np.isfinite(valid_shift(market.high, 1, valid)),
            20,
        )
        previous_close = valid_shift(market.close, 1, valid)
        amount = market.field("amount")
        raw_close = market.field("raw_close")
        float_shares = market.field("float_shares")
        entry = (
            (market.close > prior_high)
            & (amount > np.float32(100_000_000.0))
            & (market.close > market.open)
            & (market.close > previous_close)
        )
        score = np.zeros(market.shape, dtype=np.float32)
        market_cap = raw_close * float_shares
        np.copyto(score, market_cap, where=entry & np.isfinite(market_cap))
        return make_signal_matrix(
            market.shape,
            entry=entry.astype(np.uint8),
            score=score,
            entry_signal_code=np.where(entry, 0, -1).astype(np.int16),
            entry_signal_ids=("sequoia_turtle_breakout",),
        )


MATRIX_STRATEGY = SequoiaTurtleTradeStrategy()
