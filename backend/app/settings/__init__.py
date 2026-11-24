"""设置域门面：唯一的一份可持久化配置文档。

跨包只允许 `from app.settings import ...`；HTTP 层不得直接读表。
"""

from app.settings.model import SettingsRow
from app.settings.service import (
    DEFAULT_DATA_SOURCES,
    HOMEPAGE_PINNED_LIMIT,
    SettingsRecord,
    apply_saved_settings,
    load_settings,
    normalize_homepage_pinned,
    save_settings,
)

__all__ = [
    "DEFAULT_DATA_SOURCES",
    "HOMEPAGE_PINNED_LIMIT",
    "SettingsRecord",
    "SettingsRow",
    "apply_saved_settings",
    "load_settings",
    "normalize_homepage_pinned",
    "save_settings",
]
