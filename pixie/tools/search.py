"""Web search in the background: DuckDuckGo (free, no API key) + local LLM summary."""

from __future__ import annotations

from .. import llm
from ..config import CONFIG
from . import Info, tool


def _ddg(query: str, n: int) -> list[dict]:
    try:
        from ddgs import DDGS
    except ImportError:  # older package name
        from duckduckgo_search import DDGS
    return list(DDGS().text(query, max_results=n))


@tool(
    "web_search",
    "Search the internet and give a short answer. Use for facts, news, prices, weather, how-tos.",
    {"query": {"type": "string", "description": "The search query"}},
    ["query"],
)
def web_search(query: str) -> str:
    results = _ddg(query, int(CONFIG["search"]["max_results"]))
    if not results:
        return f"No results for '{query}'."
    sources = "\n\n".join(
        f"[{i + 1}] {r.get('title', '')}\n{r.get('body', '')}\n{r.get('href', '')}"
        for i, r in enumerate(results)
    )
    return Info(llm.complete(
        f"Question: {query}\n\nSearch results:\n{sources}\n\n"
        "Answer the question in 2-4 short sentences using only these results. "
        "End with the most useful source link.",
        system="You summarize web search results accurately and briefly.",
    ))
