"""研究记录域：假设、结论、决策与复盘的 CRUD 与关联。

跨包只允许 `from app.research import ...`。
"""

from app.research.model import ResearchNoteRow
from app.research.service import (
    ResearchNoteRecord,
    create_note,
    delete_note,
    get_note,
    list_notes,
    update_note,
)

__all__ = [
    "ResearchNoteRecord",
    "ResearchNoteRow",
    "create_note",
    "delete_note",
    "get_note",
    "list_notes",
    "update_note",
]
