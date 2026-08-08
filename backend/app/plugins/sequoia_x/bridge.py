"""Sequoia-X 插件依赖探测。"""
from __future__ import annotations

import importlib


def load_baostock():
    """延迟导入 Baostock, 避免未安装插件时影响主流程。"""
    return importlib.import_module("baostock")


def load_akshare():
    """延迟导入 AkShare; 定增事件按需使用。"""
    return importlib.import_module("akshare")


def availability() -> tuple[bool, str]:
    """Baostock 可用即可注册日 K provider; AkShare 缺失只影响定增事件。"""
    try:
        load_baostock()
    except ImportError:
        return False, "未安装 baostock; 请安装 sequoia extra"

    try:
        load_akshare()
    except ImportError:
        return True, "日 K 可用; AkShare 未安装, 定增事件不可用"
    return True, "ok"
