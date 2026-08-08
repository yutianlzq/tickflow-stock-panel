from __future__ import annotations

import datetime as dt

import polars as pl
import pytest

from app.plugins.sequoia_x import bridge
from app.plugins.sequoia_x.provider import SequoiaXProvider


class _ResultSet:
    def __init__(self, fields: list[str], rows: list[list[str]], *, error_code: str = "0"):
        self.fields = fields
        self.error_code = error_code
        self.error_msg = "mock error" if error_code != "0" else ""
        self._rows = iter(rows)
        self._current: list[str] | None = None

    def next(self) -> bool:
        try:
            self._current = next(self._rows)
            return True
        except StopIteration:
            self._current = None
            return False

    def get_row_data(self) -> list[str]:
        assert self._current is not None
        return self._current


class _LoginResult:
    def __init__(self, error_code: str = "0"):
        self.error_code = error_code
        self.error_msg = "login failed" if error_code != "0" else ""


class _FakeBaoStock:
    def __init__(self) -> None:
        self.history_calls: list[dict] = []
        self.logout_calls = 0

    def login(self) -> _LoginResult:
        return _LoginResult()

    def logout(self) -> None:
        self.logout_calls += 1

    def query_history_k_data_plus(self, code: str, fields: str, **kwargs) -> _ResultSet:
        self.history_calls.append({"code": code, "fields": fields, **kwargs})
        return _ResultSet(
            fields.split(","),
            [["2026-01-05", "10", "11", "9", "10.5", "123400", "1295700"]],
        )

    def query_stock_basic(self, code_name: str = "", code: str = "") -> _ResultSet:
        del code_name, code
        return _ResultSet(
            ["code", "code_name", "ipoDate", "outDate", "type", "status"],
            [
                ["sh.600519", "贵州茅台", "2001-08-27", "", "1", "1"],
                ["sz.000001", "平安银行", "1991-04-03", "", "1", "1"],
                ["sh.000001", "上证指数", "", "", "2", "1"],
                ["bj.430047", "北交样例", "", "", "1", "1"],
                ["sz.000002", "已退市样例", "", "2025-01-01", "1", "0"],
            ],
        )


def test_daily_uses_unadjusted_baostock_and_normalizes_units(monkeypatch):
    fake = _FakeBaoStock()
    monkeypatch.setattr(bridge, "load_baostock", lambda: fake)
    monkeypatch.setenv("SEQUOIA_BAOSTOCK_WORKERS", "1")

    df = SequoiaXProvider().get_daily(
        ["600519.SH"],
        dt.datetime(2026, 1, 1),
        dt.datetime(2026, 1, 6),
    )

    assert df.columns == ["symbol", "date", "open", "high", "low", "close", "volume", "amount"]
    assert df.schema["date"] == pl.Date
    assert df["symbol"].to_list() == ["600519.SH"]
    assert df["volume"].to_list() == pytest.approx([1234.0])
    assert df["amount"].to_list() == pytest.approx([1_295_700.0])
    assert fake.history_calls == [{
        "code": "sh.600519",
        "fields": "date,open,high,low,close,volume,amount",
        "start_date": "2026-01-01",
        "end_date": "2026-01-06",
        "frequency": "d",
        "adjustflag": "3",
    }]
    assert fake.logout_calls == 1


def test_daily_rejects_non_stock_assets_and_unsupported_exchange(monkeypatch):
    fake = _FakeBaoStock()
    monkeypatch.setattr(bridge, "load_baostock", lambda: fake)
    monkeypatch.setenv("SEQUOIA_BAOSTOCK_WORKERS", "1")
    provider = SequoiaXProvider()

    assert provider.get_daily(["510300.SH"], None, None, asset_type="etf").is_empty()
    with pytest.raises(ValueError, match="沪深 A 股"):
        provider.get_daily(["430047.BJ"], None, None)


def test_instruments_only_returns_active_shanghai_and_shenzhen_stocks(monkeypatch):
    fake = _FakeBaoStock()
    monkeypatch.setattr(bridge, "load_baostock", lambda: fake)

    rows = SequoiaXProvider().get_instruments("stock")

    assert rows == [
        {
            "symbol": "600519.SH",
            "name": "贵州茅台",
            "code": "600519",
            "exchange": "SH",
            "region": "CN",
            "type": "stock",
            "ext": {"listing_date": "2001-08-27"},
        },
        {
            "symbol": "000001.SZ",
            "name": "平安银行",
            "code": "000001",
            "exchange": "SZ",
            "region": "CN",
            "type": "stock",
            "ext": {"listing_date": "1991-04-03"},
        },
    ]
    assert fake.logout_calls == 1


def test_daily_partial_failure_keeps_successful_symbols(monkeypatch, caplog):
    def fake_fetch(tasks):
        assert len(tasks) == 2
        return ([{
            "symbol": "600519.SH",
            "date": "2026-01-05",
            "open": 10.0,
            "high": 11.0,
            "low": 9.0,
            "close": 10.5,
            "volume": 1234.0,
            "amount": 1_295_700.0,
        }], ["000001.SZ"])

    monkeypatch.setattr("app.plugins.sequoia_x.provider._fetch_daily_chunk", fake_fetch)
    monkeypatch.setenv("SEQUOIA_BAOSTOCK_WORKERS", "1")

    df = SequoiaXProvider().get_daily(["600519.SH", "000001.SZ"], None, None)

    assert df["symbol"].to_list() == ["600519.SH"]
    assert "部分失败" in caplog.text
    assert "000001.SZ" in caplog.text


def test_daily_login_failure_returns_empty_and_closes_session(monkeypatch):
    class _LoginFailure(_FakeBaoStock):
        def login(self) -> _LoginResult:
            return _LoginResult("1")

    fake = _LoginFailure()
    monkeypatch.setattr(bridge, "load_baostock", lambda: fake)
    monkeypatch.setenv("SEQUOIA_BAOSTOCK_WORKERS", "1")

    df = SequoiaXProvider().get_daily(["600519.SH"], None, None)

    assert df.is_empty()
    assert fake.logout_calls == 1


def test_daily_query_failure_isolated_as_empty_result(monkeypatch, caplog):
    class _QueryFailure(_FakeBaoStock):
        def query_history_k_data_plus(self, code: str, fields: str, **kwargs) -> _ResultSet:
            del code, fields, kwargs
            return _ResultSet([], [], error_code="2")

    fake = _QueryFailure()
    monkeypatch.setattr(bridge, "load_baostock", lambda: fake)
    monkeypatch.setenv("SEQUOIA_BAOSTOCK_WORKERS", "1")

    df = SequoiaXProvider().get_daily(["600519.SH"], None, None)

    assert df.is_empty()
    assert "部分失败" in caplog.text
    assert fake.logout_calls == 1


def test_unsupported_dataset_is_rejected_without_network_call():
    with pytest.raises(ValueError, match="不支持数据集"):
        SequoiaXProvider().test_dataset("adj_factor")


def test_instruments_missing_dependency_isolated(monkeypatch, caplog):
    def load_missing():
        raise ImportError("baostock missing")

    monkeypatch.setattr(bridge, "load_baostock", load_missing)

    assert SequoiaXProvider().get_instruments("stock") == []
    assert "依赖或登录失败" in caplog.text


def test_worker_failure_isolated_to_failed_batch(monkeypatch, caplog):
    monkeypatch.setattr(
        "app.plugins.sequoia_x.provider._fetch_daily_chunk",
        lambda tasks: (_ for _ in ()).throw(RuntimeError("worker failed")),
    )
    monkeypatch.setenv("SEQUOIA_BAOSTOCK_WORKERS", "1")

    df = SequoiaXProvider().get_daily(["600519.SH"], None, None)

    assert df.is_empty()
    assert "批次失败" in caplog.text


    from app.plugins.sequoia_x.events import _symbol_from_code

    assert _symbol_from_code("688001") == ("688001.SH", "688001")
    assert _symbol_from_code("430047") == ("430047.BJ", "430047")
    assert _symbol_from_code("830001") == ("830001.BJ", "830001")
    assert _symbol_from_code("300001") == ("300001.SZ", "300001")
    assert _symbol_from_code("invalid") is None


def test_plugin_is_discovered_without_forcing_dependency_install():
    from app.data_providers import custom as custom_sources

    plugins = {item["name"]: item for item in custom_sources.list_plugins()}
    assert plugins["sequoia_x"]["runtime"] == "python"
    assert plugins["sequoia_x"]["datasets"] == ["daily"]
    assert custom_sources.is_builtin("sequoia_x")
