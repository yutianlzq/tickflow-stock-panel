"""牢牛战法 — 2/3 连板首次断板后的强势修复候选。"""

import numpy as np

from app.backtest.matrix import (
    MarketDataMatrix,
    SignalMatrix,
    make_signal_matrix,
    valid_rolling_mean,
    valid_shift,
)

META = {
    "id": "laoniu_strategy",
    "name": "牢牛战法",
    "description": "筛选2/3连板后首次断板且趋势未破坏的强势核心股; 次日关注动态MA5附近修复机会",
    "tags": ["短线", "断板修复", "T+1", "龙头低吸"],
    "asset_types": ["stock"],
    "timeframes": ["1d"],
    "basic_filter": {
        "price_min": 3,
        "price_max": 200,
        "market_cap_min": 10e8,
        "amount_min": 0.5e8,
        "exclude_st": True,
        "exclude_new_days": 30,
    },
    "params": [],
    # 策略内部按原始规则生成 0-100 分; 框架直接使用该分数排序。
    "scoring": {},
    "order_by": "score",
    "descending": True,
    "limit": 20,
}

EXECUTION_BACKEND = "matrix_native"
ENTRY_SIGNALS = ["laoniu_first_break"]
EXIT_SIGNALS = []
STOP_LOSS = -0.06
MAX_HOLD_DAYS = 1
ALERTS = []


class LaoniuMatrixStrategy:
    def required_fields(self) -> frozenset[str]:
        return frozenset({"open", "high", "low", "close", "amount"})

    def required_warmup_bars(self, params: dict) -> int:
        del params
        return 20

    def compute_signals(self, market: MarketDataMatrix, params: dict) -> SignalMatrix:
        del params
        valid = np.isfinite(market.close)
        close = market.close
        previous_close = valid_shift(close, 1, valid)
        close_5d_ago = valid_shift(close, 5, valid)
        ma5 = valid_rolling_mean(close, valid, 5)
        ma10 = valid_rolling_mean(close, valid, 10)
        ma20 = valid_rolling_mean(close, valid, 20)

        limit_up = market.limit_up_locked.astype(np.float32)
        lu_1 = valid_shift(limit_up, 1, valid) > 0.5
        lu_2 = valid_shift(limit_up, 2, valid) > 0.5
        lu_3 = valid_shift(limit_up, 3, valid) > 0.5
        lu_4 = valid_shift(limit_up, 4, valid) > 0.5
        exact_2_board = lu_1 & lu_2 & ~lu_3
        exact_3_board = lu_1 & lu_2 & lu_3 & ~lu_4

        ret_1d = close / previous_close - np.float32(1.0)
        ret_5d = close / close_5d_ago - np.float32(1.0)
        candle_range = np.maximum(market.high - market.low, np.float32(0.01))
        lower_shadow_ratio = (
            np.minimum(market.open, close) - market.low
        ) / candle_range

        trend_is_intact = (
            (close > ma10)
            & (ma5 > ma10)
            & (ma10 > ma20)
        )
        break_quality = (
            (ret_1d > np.float32(-0.075))
            & (lower_shadow_ratio <= np.float32(0.45))
        )
        entry = (
            valid
            & ~market.limit_up_locked.astype(bool)
            & (exact_2_board | exact_3_board)
            & trend_is_intact
            & break_quality
        )

        amount = market.field("amount")
        score = (
            np.where(exact_3_board, 30.0, 24.0)
            + np.where((ma5 > ma10) & (ma10 > ma20), 20.0, 10.0)
            + np.where(ret_1d >= -0.03, 20.0, np.where(ret_1d >= -0.06, 14.0, 8.0))
            + np.where(
                lower_shadow_ratio <= 0.25,
                10.0,
                np.where(lower_shadow_ratio <= 0.45, 6.0, 0.0),
            )
            + np.where(ret_5d >= 0.20, 15.0, np.where(ret_5d >= 0.12, 10.0, 5.0))
            + np.where(amount >= 2e8, 5.0, 2.0)
        ).astype(np.float32)
        score[~entry] = 0.0
        score[~np.isfinite(score)] = 0.0

        return make_signal_matrix(
            market.shape,
            entry=entry.astype(np.uint8),
            score=score,
            entry_signal_code=np.where(entry, 0, -1).astype(np.int16),
            entry_signal_ids=("laoniu_first_break",),
        )


MATRIX_STRATEGY = LaoniuMatrixStrategy()
