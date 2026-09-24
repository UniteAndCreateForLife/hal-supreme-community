"""
HAL free web search — DuckDuckGo via ddgs, with Wikipedia + DDG HTML lite fallback.
No API keys. Returns OpenAI-tool-friendly JSON strings.
"""
from __future__ import annotations

import json
import logging
import re
import urllib.parse
import urllib.request
from typing import Any, Optional

logger = logging.getLogger("hal.web_search")

WEB_SEARCH_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": (
            "Search the live public web (DuckDuckGo). Use for current events, dates, "
            "news, prices, people/facts that may change, and anything after your knowledge "
            "cutoff. Returns title/url/snippet objects. Always cite sources as markdown links."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query string",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Number of results to return (1-8, default 5)",
                    "default": 5,
                    "minimum": 1,
                    "maximum": 8,
                },
            },
            "required": ["query"],
        },
    },
}

_UA = "HAL-Supreme-Gateway/1.0 (+https://halsupreme.com; free-search)"


def _clamp_max(n: Any, default: int = 5) -> int:
    try:
        v = int(n)
    except (TypeError, ValueError):
        v = default
    return max(1, min(8, v))


def _normalize_rows(rows: list[dict]) -> list[dict]:
    out: list[dict] = []
    for row in rows:
        title = str(row.get("title") or row.get("Title") or "").strip()
        url = str(
            row.get("url")
            or row.get("href")
            or row.get("link")
            or row.get("Url")
            or ""
        ).strip()
        snippet = str(
            row.get("snippet")
            or row.get("body")
            or row.get("description")
            or row.get("content")
            or ""
        ).strip()
        if not (title or url or snippet):
            continue
        out.append({"title": title or url, "url": url, "snippet": snippet[:500]})
    return out


def _search_ddgs(query: str, max_results: int) -> list[dict]:
    try:
        from ddgs import DDGS  # preferred package name
    except ImportError:
        from duckduckgo_search import DDGS  # type: ignore

    rows: list[dict] = []
    try:
        with DDGS() as client:
            # ddgs / duckduckgo_search both expose .text
            for item in client.text(query, max_results=max_results) or []:
                if isinstance(item, dict):
                    rows.append(item)
    except Exception as exc:
        # ddgs raises on empty/rate-limit; treat as empty so fallbacks run
        msg = str(exc).lower()
        if 'no results' in msg or 'not found' in msg:
            return []
        raise
    return _normalize_rows(rows)


def _search_wikipedia(query: str, max_results: int) -> list[dict]:
    q = urllib.parse.quote(query)
    url = (
        "https://en.wikipedia.org/w/api.php"
        f"?action=opensearch&search={q}&limit={max_results}&namespace=0&format=json"
    )
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=12) as resp:
        data = json.loads(resp.read().decode("utf-8", errors="replace"))
    if not isinstance(data, list) or len(data) < 4:
        return []
    titles, descs, urls = data[1], data[2], data[3]
    rows = []
    for i, title in enumerate(titles):
        rows.append(
            {
                "title": title,
                "url": urls[i] if i < len(urls) else "",
                "snippet": descs[i] if i < len(descs) else f"Wikipedia: {title}",
            }
        )
    # Enrich empty snippets with a short extract
    enriched: list[dict] = []
    for row in rows[:max_results]:
        if not row.get("snippet"):
            try:
                t = urllib.parse.quote(row["title"].replace(" ", "_"))
                ex_url = (
                    "https://en.wikipedia.org/api/rest_v1/page/summary/"
                    + urllib.parse.quote(row["title"])
                )
                ex_req = urllib.request.Request(ex_url, headers={"User-Agent": _UA})
                with urllib.request.urlopen(ex_req, timeout=8) as ex_resp:
                    summary = json.loads(ex_resp.read().decode("utf-8", errors="replace"))
                row["snippet"] = str(summary.get("extract") or "")[:400]
                if not row.get("url"):
                    row["url"] = str(
                        (summary.get("content_urls") or {})
                        .get("desktop", {})
                        .get("page")
                        or ""
                    )
            except Exception:
                row["snippet"] = f"Wikipedia article: {row['title']}"
        enriched.append(row)
    return _normalize_rows(enriched)


def _search_ddg_html(query: str, max_results: int) -> list[dict]:
    """Lightweight HTML scrape of DuckDuckGo lite — last-resort free fallback."""
    q = urllib.parse.quote_plus(query)
    url = f"https://lite.duckduckgo.com/lite/?q={q}"
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=15) as resp:
        html = resp.read().decode("utf-8", errors="replace")
    rows: list[dict] = []
    # lite results: <a rel="nofollow" href="...">title</a> near snippet td
    link_re = re.compile(
        r'<a[^>]+rel="nofollow"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
        re.I | re.S,
    )
    for m in link_re.finditer(html):
        href = m.group(1).strip()
        title = re.sub(r"<[^>]+>", "", m.group(2)).strip()
        if not href.startswith("http"):
            continue
        if "duckduckgo.com" in href:
            continue
        rows.append({"title": title or href, "url": href, "snippet": ""})
        if len(rows) >= max_results:
            break
    return _normalize_rows(rows)


def run_web_search(query: str, max_results: int = 5) -> list[dict]:
    """Execute free web search with cascading fallbacks. Never raises for empty."""
    q = (query or "").strip()
    if not q:
        return []
    n = _clamp_max(max_results)
    errors: list[str] = []

    for name, fn in (
        ("ddgs", _search_ddgs),
        ("wikipedia", _search_wikipedia),
        ("ddg_html", _search_ddg_html),
    ):
        try:
            rows = fn(q, n)
            if rows:
                logger.info("web_search ok via %s query=%r n=%d", name, q[:80], len(rows))
                return rows[:n]
            errors.append(f"{name}:empty")
        except Exception as exc:
            errors.append(f"{name}:{type(exc).__name__}:{exc}")
            logger.warning("web_search %s failed: %s", name, exc)

    logger.warning("web_search all backends failed query=%r errors=%s", q[:80], errors)
    return []


def web_search_tool_result(query: str, max_results: int = 5) -> str:
    """JSON string for tool role content."""
    rows = run_web_search(query, max_results)
    return json.dumps(rows, ensure_ascii=False)


def format_search_context(query: str, rows: list[dict]) -> str:
    """Human-readable block to inject for models that cannot tool-call well."""
    if not rows:
        return (
            f"[Live web search for {query!r} returned no results. "
            "Say so briefly and answer from general knowledge without inventing URLs.]"
        )
    lines = [f"[Live web search results for {query!r}]"]
    for i, row in enumerate(rows, 1):
        lines.append(f"{i}. {row.get('title') or 'Result'} — {row.get('url') or ''}")
        sn = (row.get("snippet") or "").strip()
        if sn:
            lines.append(f"   {sn}")
    lines.append(
        "Use these results when relevant. Cite sources with markdown links like "
        "[Title](https://example.com)."
    )
    return "\n".join(lines)


_SEARCH_HINT_RE = re.compile(
    r"\b("
    r"today|tonight|yesterday|tomorrow|current|currently|latest|breaking|headline|news|"
    r"weather|stock|price|who\s+won|what\s+happened|as\s+of|right\s+now|this\s+week|"
    r"this\s+month|live|update|updated|cite|citation|source|sources|url|website|"
    r"search\s+(the\s+)?web|look\s+up|google|duckduckgo|"
    r"20(2[4-9]|3[0-9])"  # years 2024-2039 as currency hint
    r")\b",
    re.I,
)


def message_needs_search(text: str) -> bool:
    """Heuristic for local/fast models that should not rely on tool-calling."""
    if not text:
        return False
    return bool(_SEARCH_HINT_RE.search(text))


def execute_tool_call(name: str, arguments: Any) -> str:
    """Dispatch a single tool call by name. Returns JSON/string content for tool message."""
    if name == "generate_image":
        from hal_model_gateway.image_gen import execute_generate_image
        return execute_generate_image(arguments)
    if name == "run_code":
        from hal_model_gateway.run_code import execute_run_code
        return execute_run_code(arguments)
    if name != "web_search":
        return json.dumps({"error": f"unknown tool: {name}"})
    args = arguments
    if isinstance(args, str):
        try:
            args = json.loads(args) if args.strip() else {}
        except json.JSONDecodeError:
            args = {"query": args}
    if not isinstance(args, dict):
        args = {}
    query = str(args.get("query") or "").strip()
    max_results = _clamp_max(args.get("max_results", 5))
    if not query:
        return json.dumps({"error": "query is required"})
    return web_search_tool_result(query, max_results)
