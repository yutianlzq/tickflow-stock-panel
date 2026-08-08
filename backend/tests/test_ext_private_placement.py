from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest

from app.api.analysis import _default_menus
from app.plugins.sequoia_x import events
from app.services.ext_data import ExtConfigStore, rows_to_parquet
from app.services.ext_presets import get_preset


def test_private_placement_filters_recent_directional_rows_and_deduplicates(monkeypatch):
    today = date(2026, 8, 8)
    raw = pd.DataFrame([
        {
            "股票代码": "600519",
            "股票简称": "贵州茅台",
            "发行方式": "定向增发",
            "发行日期": today - timedelta(days=1),
            "发行价格": 1000.0,
            "发行数量": 10_000.0,
            "募集资金": 10_000_000.0,
        },
        {
            "股票代码": "600519",
            "股票简称": "贵州茅台",
            "发行方式": "定向增发",
            "发行日期": today - timedelta(days=3),
            "发行价格": 900.0,
            "发行数量": 8_000.0,
            "募集资金": 7_200_000.0,
        },
        {
            "股票代码": "000001",
            "股票简称": "平安银行",
            "发行方式": "公开增发",
            "发行日期": today,
        },
        {
            "股票代码": "430047",
            "股票简称": "北交样例",
            "发行方式": "定向增发",
            "发行日期": today - timedelta(days=7),
            "发行价格": 8.0,
        },
        {
            "股票代码": "300001",
            "股票简称": "过期样例",
            "发行方式": "定向增发",
            "发行日期": today - timedelta(days=8),
        },
    ])
    monkeypatch.setattr(events.bridge, "load_akshare", lambda: type(
        "FakeAkshare",
        (),
        {"stock_qbzf_em": staticmethod(lambda: raw)},
    ))

    rows = events.fetch_private_placements(today=today, lookback_days=7)

    assert rows == [
        {
            "symbol": "600519.SH",
            "code": "600519",
            "股票简称": "贵州茅台",
            "发行方式": "定向增发",
            "发行日期": "2026-08-07",
            "发行价格": 1000.0,
            "发行数量": 10_000.0,
            "募集资金": 10_000_000.0,
        },
        {
            "symbol": "430047.BJ",
            "code": "430047",
            "股票简称": "北交样例",
            "发行方式": "定向增发",
            "发行日期": "2026-08-01",
            "发行价格": 8.0,
            "发行数量": None,
            "募集资金": None,
        },
    ]


def test_private_placement_accepts_akshare_field_aliases(monkeypatch):
    raw = pd.DataFrame([{
        "代码": "300001",
        "名称": "特锐德",
        "发行类型": "定向增发",
        "增发发行日期": "2026-08-08",
        "增发价格": "12.3",
        "实际发行数量": "100",
        "实际募集资金": "1230",
    }])
    monkeypatch.setattr(events.bridge, "load_akshare", lambda: type(
        "FakeAkshare",
        (),
        {"stock_qbzf_em": staticmethod(lambda: raw)},
    ))

    rows = events.fetch_private_placements(today=date(2026, 8, 8))

    assert rows[0]["symbol"] == "300001.SZ"
    assert rows[0]["发行价格"] == pytest.approx(12.3)
    assert rows[0]["发行数量"] == pytest.approx(100.0)
    assert rows[0]["募集资金"] == pytest.approx(1230.0)


def test_private_placement_rejects_missing_contract_fields(monkeypatch):
    monkeypatch.setattr(events.bridge, "load_akshare", lambda: type(
        "FakeAkshare",
        (),
        {"stock_qbzf_em": staticmethod(lambda: pd.DataFrame([{"未知字段": "x"}]))},
    ))

    with pytest.raises(ValueError, match="缺少"):
        events.fetch_private_placements(today=date(2026, 8, 8))


def test_private_placement_fetch_replaces_previous_snapshot(monkeypatch, tmp_path):
    preset = get_preset("ext_private_placement")
    assert preset is not None
    ExtConfigStore(tmp_path).upsert(preset)
    rows_to_parquet([{
        "symbol": "000001.SZ",
        "code": "000001",
        "股票简称": "旧事件",
        "发行方式": "定向增发",
        "发行日期": "2026-07-01",
        "发行价格": 1.0,
        "发行数量": 1.0,
        "募集资金": 1.0,
    }], preset, tmp_path, replace_snapshot=True)
    monkeypatch.setattr(
        "app.plugins.sequoia_x.events.fetch_private_placements",
        lambda: [{
            "symbol": "600519.SH",
            "code": "600519",
            "股票简称": "新事件",
            "发行方式": "定向增发",
            "发行日期": "2026-08-08",
            "发行价格": 2.0,
            "发行数量": 2.0,
            "募集资金": 4.0,
        }],
    )

    import asyncio

    from app.services.ext_presets import fetch_preset

    asyncio.run(fetch_preset("ext_private_placement", tmp_path))
    stored = pd.read_parquet(tmp_path / "ext_data" / "ext_private_placement" / "part.parquet")

    assert stored["symbol"].tolist() == ["600519.SH"]


def test_private_placement_snapshot_write_uses_atomic_replace(monkeypatch, tmp_path):
    preset = get_preset("ext_private_placement")
    assert preset is not None
    ExtConfigStore(tmp_path).upsert(preset)

    write_calls: list[str] = []
    original_replace = Path.replace

    def record_replace(self, target):
        write_calls.append(self.name)
        return original_replace(self, target)

    monkeypatch.setattr(Path, "replace", record_replace)
    rows_to_parquet([{
        "symbol": "600519.SH",
        "code": "600519",
        "股票简称": "贵州茅台",
        "发行方式": "定向增发",
        "发行日期": "2026-08-08",
        "发行价格": 2.0,
        "发行数量": 2.0,
        "募集资金": 4.0,
    }], preset, tmp_path, replace_snapshot=True)

    assert write_calls
    assert (tmp_path / "ext_data" / "ext_private_placement" / "part.parquet").exists()


    preset = get_preset("ext_private_placement")
    assert preset is not None
    ExtConfigStore(tmp_path).upsert(preset)

    class _Store:
        data_dir = tmp_path

    class _Repo:
        store = _Store()

    class _State:
        repo = _Repo()

    class _App:
        state = _State()

    class _Request:
        app = _App()

    menus = _default_menus(_Request())

    assert len(menus) == 1
    menu = menus[0]
    assert menu.id == "private_placement"
    assert menu.data_source == "ext_private_placement"
    assert menu.template == "table"
    assert menu.default_sort is not None
    assert menu.default_sort.field == "发行日期"
    assert menu.builtin is True


def test_private_placement_preset_is_builtin_snapshot():
    preset = get_preset("ext_private_placement")

    assert preset is not None
    assert preset.mode == "snapshot"
    assert preset.pull is None
    assert [field.name for field in preset.fields] == [
        "symbol",
        "code",
        "股票简称",
        "发行方式",
        "发行日期",
        "发行价格",
        "发行数量",
        "募集资金",
    ]
