"""牢牛战法 4.2 — 2/3 连板首次断板后的技术候选池。"""

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
    "description": "筛选2/3连板后首次断板且短线趋势未明显破坏的候选股; 按断板强度、趋势和MA5位置排序",
    "tags": ["短线", "断板修复", "T+1", "龙头低吸"],
    "asset_types": ["stock"],
    "timeframes": ["1d"],
    "basic_filter": {
        "price_min": 3,
        "price_max": 200,
        "market_cap_min": 10e8,
        "amount_min": 1e8,
        "exclude_st": True,
        "exclude_new_days": 30,
    },
    "params": [
        {
            "id": "max_break_drop",
            "label": "断板最大跌幅",
            "type": "float",
            "default": -0.075,
            "min": -0.12,
            "max": -0.03,
            "step": 0.005,
        },
        {
            "id": "max_below_ma5",
            "label": "允许跌破MA5幅度",
            "type": "float",
            "default": -0.03,
            "min": -0.08,
            "max": 0,
            "step": 0.005,
        },
        {
            "id": "max_lower_shadow",
            "label": "最大下影比例",
            "type": "float",
            "default": 0.45,
            "min": 0.2,
            "max": 0.8,
            "step": 0.05,
        },
    ],
    # 策略内部生成 0-100 分纯技术分; 框架直接使用该分数排序。
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


def _break_score(ret_1d: np.ndarray) -> np.ndarray:
    return np.where(
        ret_1d >= 0.05,
        30.0,
        np.where(
            ret_1d >= 0.03,
            28.0,
            np.where(
                ret_1d >= 0.0,
                25.0,
                np.where(
                    ret_1d >= -0.03,
                    19.0,
                    np.where(ret_1d >= -0.05, 12.0, 5.0),
                ),
            ),
        ),
    )


def _ma5_score(ma5_gap: np.ndarray) -> np.ndarray:
    return np.where(
        (ma5_gap >= 0.0) & (ma5_gap <= 0.08),
        10.0,
        np.where(
            (ma5_gap > 0.08) & (ma5_gap <= 0.15),
            8.0,
            np.where(
                (ma5_gap >= -0.03) & (ma5_gap < 0.0),
                7.0,
                np.where(ma5_gap > 0.15, 3.0, 0.0),
            ),
        ),
    )


class LaoniuMatrixStrategy:
    def required_fields(self) -> frozenset[str]:
        return frozenset({"open", "high", "low", "close", "amount"})

    def required_warmup_bars(self, params: dict) -> int:
        del params
        return 20

    def compute_signals(self, market: MarketDataMatrix, params: dict) -> SignalMatrix:
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
        ma5_gap = close / ma5 - np.float32(1.0)
        candle_range = np.maximum(market.high - market.low, np.float32(0.01))
        lower_shadow_ratio = (np.minimum(market.open, close) - market.low) / candle_range

        max_break_drop = np.float32(params.get("max_break_drop", -0.075))
        max_below_ma5 = np.float32(params.get("max_below_ma5", -0.03))
        max_lower_shadow = np.float32(params.get("max_lower_shadow", 0.45))
        full_bull = (ma5 > ma10) & (ma10 > ma20)
        trend_not_broken = (
            (close >= ma5 * (np.float32(1.0) + max_below_ma5))
            & (ma5 >= ma10 * np.float32(0.97))
        )
        break_quality = (
            (ret_1d >= max_break_drop)
            & (lower_shadow_ratio <= max_lower_shadow)
        )
        entry = (
            valid
            & ~market.limit_up_locked.astype(bool)
            & (exact_2_board | exact_3_board)
            & trend_not_broken
            & break_quality
        )

        amount = market.field("amount")
        board_score = np.where(exact_3_board, 25.0, 21.0)
        trend_score = np.where(
            full_bull,
            15.0,
            np.where(ma5 > ma10, 11.0, np.where(ma5 >= ma10 * 0.97, 6.0, 0.0)),
        )
        candle_score = np.where(
            lower_shadow_ratio <= 0.20,
            10.0,
            np.where(lower_shadow_ratio <= 0.35, 7.0, np.where(lower_shadow_ratio <= 0.45, 4.0, 0.0)),
        )
        amount_score = np.where(
            amount >= 10e8,
            5.0,
            np.where(amount >= 3e8, 4.0, np.where(amount >= 1e8, 2.0, 0.0)),
        )
        momentum_score = np.where(
            ret_5d >= 0.25,
            5.0,
            np.where(ret_5d >= 0.15, 4.0, np.where(ret_5d >= 0.08, 2.0, 0.0)),
        )
        score = (
            board_score
            + _break_score(ret_1d)
            + trend_score
            + _ma5_score(ma5_gap)
            + candle_score
            + amount_score
            + momentum_score
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
