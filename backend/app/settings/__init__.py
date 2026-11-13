"""设置域门面：唯一的一份可持久化配置文档。

跨包只允许 `from app.settings import ...`；HTTP 层不得直接读表。
"""

from app.settings.model import SettingsRow
from app.settings.service import (
    SettingsRecord,
    apply_saved_settings,
    load_settings,
    save_settings,
)

__all__ = [
    "SettingsRecord",
    "SettingsRow",
    "apply_saved_settings",
    "load_settings",
    "save_settings",
]
