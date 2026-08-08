"""Sequoia-X 可选数据源插件。"""

from app.plugins.sequoia_x.bridge import availability, load_akshare, load_baostock
from app.plugins.sequoia_x.provider import SequoiaXProvider

PROVIDER_NAME = "sequoia_x"

__all__ = [
    "PROVIDER_NAME",
    "SequoiaXProvider",
    "availability",
    "load_akshare",
    "load_baostock",
]
