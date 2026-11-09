"""旧能力已移除（AC-9）：没有自然语言助手路由，也没有 LLM 调用或写意图分类。"""

import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
REPO = BACKEND.parent

# 只检查「是否引入/调用了 LLM SDK 或意图分类」，避免误伤行情域既有的
# 资产分类 `classify()` 与私有公司代码 "OPENAI-USDT-SWAP"。
LLM_IMPORT = re.compile(
    r"^\s*(?:from|import)\s+(openai|anthropic|langchain|litellm|llama_index)\b",
    re.IGNORECASE | re.MULTILINE,
)
LLM_CALL = re.compile(r"\b(openai\.|anthropic\.|litellm\.|ChatCompletion|completion\()")


async def test_assistant_routes_do_not_exist(client) -> None:
    for path in (
        "/api/assistant/query",
        "/api/v1/assistant/query",
        "/api/v1/ai/query",
        "/ai/query",
    ):
        response = await client.get(path)
        assert response.status_code == 404, path


def test_backend_declares_no_llm_dependency() -> None:
    pyproject = (BACKEND / "pyproject.toml").read_text(encoding="utf-8").lower()
    for token in ("openai", "anthropic", "langchain", "litellm", "llama-index"):
        assert token not in pyproject, token


def test_no_llm_imports_or_calls_in_app() -> None:
    offenders: list[str] = []
    for path in (BACKEND / "app").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if LLM_IMPORT.search(text) or LLM_CALL.search(text):
            offenders.append(str(path.relative_to(BACKEND)))
        assert "write_marker" not in text, path
    assert offenders == []


def test_no_assistant_module_or_intent_classifier() -> None:
    # `app/ai` 与 `app/assistant` 都不该存在（P4 改为 MCP，见 docs/adr/0007）。
    assert not (BACKEND / "app" / "ai").exists()
    assert not (BACKEND / "app" / "assistant").exists()

    for path in (BACKEND / "app").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "write_intent" not in text, path
        assert "classify_intent" not in text, path
        assert "assistant.query" not in text, path


def test_frontend_has_no_assistant_page() -> None:
    pages = REPO / "frontend" / "src" / "pages"
    assert not (pages / "assistant").exists()
    assert not (pages / "ai").exists()
