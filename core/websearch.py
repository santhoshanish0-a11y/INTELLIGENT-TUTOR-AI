"""
Live web search for time-sensitive questions (current office holders, news, exam notifications ...).

A language model only knows what it learned before its training cutoff, so for "present" facts the tutor
first fetches fresh web results and lets the model answer from them.

Providers are tried in this order until one returns results (all free, none needs a key except Tavily):
  1. Tavily          optional, TAVILY_API_KEY in .env (free tier, most reliable)
  2. DuckDuckGo      html.duckduckgo.com
  3. DuckDuckGo Lite lite.duckduckgo.com
  4. Wikipedia       en.wikipedia.org search API (always current for office holders)
Standard library only.
"""
import html
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser

TIMEOUT = 8
CACHE_SECONDS = 600
_cache = {}
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/124.0 Safari/537.36")

ABBREVIATIONS = {
    r"\bcm\b": "chief minister", r"\bpm\b": "prime minister", r"\bdcm\b": "deputy chief minister",
    r"\btamilnadu\b": "tamil nadu", r"\btn\b": "tamil nadu", r"\bup\b(?= cm| chief)": "uttar pradesh",
    r"\brbi\b": "reserve bank of india", r"\bcji\b": "chief justice of india", r"\bsc\b(?= judge)": "supreme court",
}
FILLER = r"\b(please|tell me|can you|could you|i want to know|do you know)\b"


def build_query(message, today=None):
    """Turn a chat message into a compact search query."""
    q = message.lower().strip().rstrip("?.! ")
    q = re.sub(FILLER, " ", q)
    for pattern, repl in ABBREVIATIONS.items():
        q = re.sub(pattern, repl, q)
    q = re.sub(r"^(who is|who's|who are|what is|what's|which is|name of)\s+(the\s+)?", "", q)
    q = re.sub(r"\s+", " ", q).strip()
    year = (today or time.strftime("%Y"))[:4]
    if not re.search(r"\b(current|present|latest|recent|now|today)\b", q) and (
            "who" in message.lower() or re.search(r"\b(now|present|today)\b", message.lower())):
        q = f"current {q}"
    if year not in q:
        q = f"{q} {year}"
    return q[:200]


def _http(url, data=None, headers=None):
    req = urllib.request.Request(url, data=data, headers={"User-Agent": UA, "Accept-Language": "en", **(headers or {})})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return resp.read().decode("utf-8", "ignore")


def _clean(text):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", text or ""))).strip()


# --------------------------------------------------------------------------- #
# DuckDuckGo (HTML and Lite pages share one parser)
# --------------------------------------------------------------------------- #
class _DDGParser(HTMLParser):
    TITLE = ("result__a", "result-link")
    SNIPPET = ("result__snippet", "result-snippet")

    def __init__(self):
        super().__init__()
        self.results, self._mode, self._buf, self._href = [], None, [], None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        classes = (a.get("class") or "").split()
        if any(c in classes for c in self.TITLE) and tag == "a":
            self._mode, self._buf, self._href = "title", [], a.get("href", "")
        elif any(c in classes for c in self.SNIPPET):
            self._mode, self._buf = "snippet", []

    def handle_data(self, data):
        if self._mode:
            self._buf.append(data)

    def handle_endtag(self, tag):
        if not self._mode or tag not in ("a", "td", "div"):
            return
        text = _clean("".join(self._buf))
        if self._mode == "title" and tag == "a":
            self.results.append({"title": text, "url": _real_url(self._href), "snippet": ""})
            self._mode = None
        elif self._mode == "snippet" and tag in ("a", "td", "div"):
            if self.results and not self.results[-1]["snippet"]:
                self.results[-1]["snippet"] = text
            self._mode = None


def _real_url(href):
    """DuckDuckGo wraps links as //duckduckgo.com/l/?uddg=<encoded-url>."""
    href = html.unescape(href or "")
    if href.startswith("//"):
        href = "https:" + href
    qs = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
    return qs["uddg"][0] if "uddg" in qs else href


def parse_ddg(markup):
    p = _DDGParser()
    p.feed(markup)
    return [r for r in p.results if r["title"] and r["url"].startswith("http") and "duckduckgo.com/y.js" not in r["url"]]


def _ddg_html(query):
    return parse_ddg(_http("https://html.duckduckgo.com/html/", data=urllib.parse.urlencode({"q": query}).encode()))


def _ddg_lite(query):
    return parse_ddg(_http("https://lite.duckduckgo.com/lite/", data=urllib.parse.urlencode({"q": query}).encode()))


# --------------------------------------------------------------------------- #
# Wikipedia and Tavily
# --------------------------------------------------------------------------- #
def parse_wikipedia(raw):
    out = []
    for item in json.loads(raw).get("query", {}).get("search", []):
        title = item["title"]
        out.append({"title": title + " (Wikipedia)",
                    "url": "https://en.wikipedia.org/wiki/" + urllib.parse.quote(title.replace(" ", "_")),
                    "snippet": _clean(item.get("snippet", ""))})
    return out


def _wikipedia(query):
    q = re.sub(r"\b(current|present|latest|now|today)\b", " ", query)
    url = ("https://en.wikipedia.org/w/api.php?action=query&list=search&format=json&srlimit=4&srsearch="
           + urllib.parse.quote(q))
    return parse_wikipedia(_http(url))


def parse_tavily(raw):
    data = json.loads(raw)
    out = []
    if data.get("answer"):
        out.append({"title": "Summary", "url": "", "snippet": data["answer"]})
    for r in data.get("results", []):
        out.append({"title": r.get("title", ""), "url": r.get("url", ""), "snippet": _clean(r.get("content", ""))[:500]})
    return out


def _tavily(query):
    key = os.environ.get("TAVILY_API_KEY")
    if not key:
        return []
    body = json.dumps({"query": query, "max_results": 5, "include_answer": True, "search_depth": "basic"}).encode()
    return parse_tavily(_http("https://api.tavily.com/search", data=body,
                              headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"}))


PROVIDERS = (("tavily", _tavily), ("duckduckgo", _ddg_html), ("duckduckgo-lite", _ddg_lite), ("wikipedia", _wikipedia))


def enabled():
    return os.environ.get("WEB_SEARCH", "1").strip().lower() not in ("0", "false", "off", "no")


def search(query, limit=5):
    """Return (results, provider_name). results is [] when every provider failed."""
    if not enabled():
        return [], None
    hit = _cache.get(query)
    if hit and time.time() - hit[0] < CACHE_SECONDS:
        return hit[1], hit[2]
    for name, fn in PROVIDERS:
        try:
            results = fn(query)[:limit]
        except (urllib.error.URLError, TimeoutError, ValueError, OSError, KeyError):
            continue
        if results:
            _cache[query] = (time.time(), results, name)
            return results, name
    return [], None


def format_for_prompt(results):
    lines = []
    for i, r in enumerate(results, 1):
        lines.append(f"[{i}] {r['title']}: {r['snippet'][:400]}" + (f" ({r['url']})" if r["url"] else ""))
    return "\n".join(lines)


def sources_markdown(results):
    links = [f"- [{r['title'][:90]}]({r['url']})" for r in results if r["url"].startswith("http")][:4]
    return "\n".join(links)