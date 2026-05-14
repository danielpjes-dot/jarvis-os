"""
JARVIS Skill — News by topic and optional location.

Uses Google News RSS feeds.
Returns structured UI result when supported by frontend.
Still works with old/plain text fallback through speech.summary.
"""

import html
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import Dict, List, Tuple, Any


SKILL_NAME = "news"
SKILL_DESCRIPTION = "News headlines by topic and optional location"
SKILL_VERSION = "1.2.0"
SKILL_AUTHOR = "Sami Porokka"
SKILL_CATEGORY = "utility"
SKILL_TAGS = ["news", "headlines", "location", "topic", "rss", "ui"]
SKILL_REQUIREMENTS = []
SKILL_CAPABILITIES = ["top_news", "search_news"]

SKILL_META = {
    "name": SKILL_NAME,
    "description": SKILL_DESCRIPTION,
    "version": SKILL_VERSION,
    "author": SKILL_AUTHOR,
    "category": SKILL_CATEGORY,
    "tags": SKILL_TAGS,
    "requirements": SKILL_REQUIREMENTS,
    "capabilities": SKILL_CAPABILITIES,
    "writes_files": False,
    "reads_files": False,
    "network_access": True,
    "entrypoint": "exec_news",
    "route": "tools",
    "intent_aliases": ["news", "headlines", "latest news", "top stories"],
    "keywords": ["news", "headlines", "latest news", "what's happening", "top stories", "local news"],
    "direct_match": ["news", "headlines", "latest news", "top stories"],
    "response_style": {
        "default": "structured_news_ui",
        "avoid_raw_dump": True,
        "followup_hint": True,
    },
}

GOOGLE_NEWS_SEARCH = "https://news.google.com/rss/search"
GOOGLE_NEWS_TOP = "https://news.google.com/rss"

LANG_BY_LOCATION = {
    "estonia": ("en-US", "US:en"),
    "tallinn": ("en-US", "US:en"),
    "finland": ("en-US", "US:en"),
    "helsinki": ("en-US", "US:en"),
    "sweden": ("en-US", "US:en"),
    "stockholm": ("en-US", "US:en"),
    "uk": ("en-GB", "GB:en"),
    "united kingdom": ("en-GB", "GB:en"),
    "london": ("en-GB", "GB:en"),
    "usa": ("en-US", "US:en"),
    "united states": ("en-US", "US:en"),
    "new york": ("en-US", "US:en"),
}


def _clean_text(text: str) -> str:
    text = html.unescape((text or "").strip())
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _clean_title(title: str, source: str = "") -> str:
    title = _clean_text(title)

    if source:
        suffix = f" - {source}"
        if title.endswith(suffix):
            title = title[: -len(suffix)].strip()

    return title.strip(" -–—")


def _shorten(text: str, max_len: int = 180) -> str:
    text = _clean_text(text)
    if len(text) <= max_len:
        return text
    return text[:max_len].rsplit(" ", 1)[0].rstrip(" ,.-") + "..."


def _lang_region(location: str) -> Tuple[str, str]:
    key = (location or "").strip().lower()
    if key in LANG_BY_LOCATION:
        return LANG_BY_LOCATION[key]
    return ("en-US", "US:en")


def _rss_fetch(url: str, timeout: int = 12) -> List[Dict[str, str]]:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/rss+xml, application/xml, text/xml",
        },
    )

    with urllib.request.urlopen(req, timeout=timeout) as resp:
        xml_data = resp.read().decode("utf-8", errors="replace")

    root = ET.fromstring(xml_data)
    items: List[Dict[str, str]] = []

    for item in root.findall(".//item"):
        raw_title = item.findtext("title", default="")
        link = _clean_text(item.findtext("link", default=""))
        pub = _clean_text(item.findtext("pubDate", default=""))
        desc = _clean_text(item.findtext("description", default=""))

        source = ""
        source_el = item.find("source")
        if source_el is not None and source_el.text:
            source = _clean_text(source_el.text)

        title = _clean_title(raw_title, source=source)

        if title:
            items.append(
                {
                    "title": title,
                    "link": link,
                    "pubDate": pub,
                    "source": source,
                    "description": desc,
                }
            )

    return items


def _dedupe_items(items: List[Dict[str, str]]) -> List[Dict[str, str]]:
    seen = set()
    out: List[Dict[str, str]] = []

    for item in items:
        key = (item.get("title", "").lower(), item.get("source", "").lower())
        if key in seen:
            continue
        seen.add(key)
        out.append(item)

    return out


def _plain_digest(title: str, ui_items: List[Dict[str, Any]]) -> str:
    if not ui_items:
        return f"{title}:\nNo news found."

    lines = [f"{title}:", ""]
    for item in ui_items:
        source = item.get("source", "")
        headline = item.get("title", "")
        if source:
            lines.append(f"{item.get('id')}. {headline} ({source})")
        else:
            lines.append(f"{item.get('id')}. {headline}")

    lines.append("")
    lines.append("Say: summarize number 5")
    return "\n".join(lines)


def _build_news_result(title: str, items: List[Dict[str, str]], limit: int = 6) -> Dict[str, Any]:
    limit = max(1, min(int(limit), 10))
    items = _dedupe_items(items)[:limit]

    ui_items: List[Dict[str, Any]] = []
    for idx, item in enumerate(items, start=1):
        ui_items.append(
            {
                "id": idx,
                "title": _shorten(item.get("title", ""), 180),
                "source": item.get("source", "").strip(),
                "published": item.get("pubDate", "").strip(),
                "story": _shorten(item.get("description", ""), 260),
                "url": item.get("link", "").strip(),
            }
        )

    if not ui_items:
        speech = f"No news found for {title}."
    else:
        speech = f"I found {len(ui_items)} headlines for {title}."

    plain = _plain_digest(title, ui_items)

    return {
    "ok": True,
    "speech": {
        "text": speech,
        "priority": "normal",
    },
    "ui": {
        "placement": "tab",
        "format": "news",
        "title": title,
        "summary": speech,
        "items": ui_items,
        "ttl_seconds": 600,
        "closable": True,
        "actions": [
            {
                "type": "close_tab",
                "label": "Close news",
            }
        ],
    },
    "action": {
        "type": "open_tab",
        "payload": {
            "tab_id": "news",
            "label": "NEWS",
        },
    },
    "data": {
        "title": title,
        "items": ui_items,
        "plain": plain,
    },
}


def _error_result(title: str, message: str, error: str = "") -> Dict[str, Any]:
    return {
        "ok": False,
        "speech": {
            "text": message,
            "priority": "normal",
        },
        "ui": {
            "placement": "right-side-hud",
            "format": "status",
            "title": title,
            "summary": message,
            "ttl_seconds": 300,
        },
        "data": {
            "plain": f"{title}: {message}",
        },
        "error": error or message,
    }


def exec_news(action: str, topic: str = "", location: str = "", limit: int = 6) -> Dict[str, Any]:
    action = (action or "").strip().lower()
    topic = (topic or "").strip()
    location = (location or "").strip()

    try:
        limit = max(1, min(int(limit), 10))
    except Exception:
        limit = 6

    if action not in {"top", "search"}:
        return _error_result(
            "News",
            "Available news actions are top and search.",
            "invalid_action",
        )

    lang, ceid = _lang_region(location)

    try:
        if action == "top":
            if location:
                query = urllib.parse.urlencode(
                    {
                        "q": location,
                        "hl": lang,
                        "gl": lang.split("-")[-1],
                        "ceid": ceid,
                    }
                )
                url = f"{GOOGLE_NEWS_SEARCH}?{query}"
                items = _rss_fetch(url)
                return _build_news_result(f"Top news for {location}", items, limit=limit)

            query = urllib.parse.urlencode(
                {
                    "hl": lang,
                    "gl": lang.split("-")[-1],
                    "ceid": ceid,
                }
            )
            url = f"{GOOGLE_NEWS_TOP}?{query}"
            items = _rss_fetch(url)
            return _build_news_result("Top news", items, limit=limit)

        if not topic:
            return _error_result(
                "News search",
                "A topic is required for news search.",
                "topic_required",
            )

        query_text = topic
        if location:
            query_text = f"{topic} {location}"

        query = urllib.parse.urlencode(
            {
                "q": query_text,
                "hl": lang,
                "gl": lang.split("-")[-1],
                "ceid": ceid,
            }
        )
        url = f"{GOOGLE_NEWS_SEARCH}?{query}"
        items = _rss_fetch(url)

        title = f"News for {topic}"
        if location:
            title += f" in {location}"

        return _build_news_result(title, items, limit=limit)

    except Exception as e:
        return _error_result(
            "News error",
            "I could not fetch the news.",
            str(e),
        )


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "news",
            "description": "Get live news headlines. Actions: top for general/location headlines, search for topic-based news.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["top", "search"],
                        "description": "News action to perform.",
                    },
                    "topic": {
                        "type": "string",
                        "description": "Topic to search for, e.g. AI, NVIDIA, Ukraine",
                    },
                    "location": {
                        "type": "string",
                        "description": "Optional location, e.g. Tallinn, Estonia, London",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of headlines to return. Default 6.",
                    },
                },
                "required": ["action"],
                "additionalProperties": False,
            },
        },
    },
]

TOOL_MAP = {
    "news": exec_news,
}

KEYWORDS = {
    "news": [
        "news",
        "headlines",
        "latest news",
        "what's happening",
        "top stories",
        "local news",
        "news in",
    ],
}

SKILL_EXAMPLES = [
    {
        "command": "top news in Estonia",
        "tool": "news",
        "args": {"action": "top", "location": "Estonia"},
    },
    {
        "command": "latest AI news",
        "tool": "news",
        "args": {"action": "search", "topic": "AI"},
    },
    {
        "command": "Ukraine news in Europe",
        "tool": "news",
        "args": {"action": "search", "topic": "Ukraine", "location": "Europe"},
    },
]