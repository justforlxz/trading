"""活动流水域：业务动作的追加式事实记录，供首页与记录页读取。

跨包只允许 `from app.activity import ...`。
"""

from app.activity.model import ActivityEventRow
from app.activity.service import list_activity, record_activity

__all__ = ["ActivityEventRow", "list_activity", "record_activity"]
