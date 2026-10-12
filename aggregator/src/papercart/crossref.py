"""Bounded, paced Crossref metadata retrieval with isolated source failures."""

from dataclasses import dataclass, field
from datetime import date
import logging
import os
import time
from typing import Callable

import httpx

from .normalize import Paper, normalize_crossref
from .privacy import PLACEHOLDER, protect_http_logs
from .sources import Source

LOGGER = logging.getLogger(__name__)


@dataclass
class FetchResult:
    source: str
    status: str
    papers: list[Paper] = field(default_factory=list)
    pages: int = 0
    received: int = 0
    filtered: int = 0
    error: str | None = None


class CrossrefFetcher:
    def __init__(self, client: httpx.Client | None = None, *, rows: int = 100, max_pages: int = 2,
                 sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic):
        if not 1 <= max_pages <= 2 or not 1 <= rows <= 1000:
            raise ValueError("Use 1–2 pages and 1–1000 rows")
        protect_http_logs()
        self._owned_client = client is None
        self.client = client or httpx.Client(timeout=30, follow_redirects=False, headers={"User-Agent": "PaperCart/0.1 (metadata only)"})
        self.rows, self.max_pages = rows, max_pages
        self.sleep, self.clock = sleep, clock
        self._next_request = 0.0
        self._mailto = os.environ.get("CROSSREF_MAILTO") or PLACEHOLDER
        if not os.environ.get("CROSSREF_MAILTO"):
            LOGGER.warning("CROSSREF_MAILTO 未设置，使用 papercart@example.invalid")

    def close(self):
        if self._owned_client:
            self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def fetch(self, source: Source, *, from_date: date) -> FetchResult:
        if not source.active:
            return FetchResult(source.id, "disabled")
        config = source.crossref
        if config is None:
            return FetchResult(source.id, "not_applicable")
        # Only construct API metadata routes. Never follow item resource URLs or redirects.
        if config.issn:
            url = f"https://api.crossref.org/journals/{config.issn}/works"
            filter_value = f"from-pub-date:{from_date.isoformat()},type:journal-article"
        else:
            url = f"https://api.crossref.org/prefixes/{config.prefix}/works"
            filter_value = f"from-pub-date:{from_date.isoformat()}"
        result = FetchResult(source.id, "empty")
        for page in range(self.max_pages):
            delay = self._next_request - self.clock()
            if delay > 0:
                self.sleep(delay)
            result.pages += 1
            try:
                response = self.client.get(url, params={
                    "filter": filter_value, "sort": "published", "order": "desc",
                    "rows": self.rows, "offset": page * self.rows, "mailto": self._mailto,
                }, follow_redirects=False)
            except httpx.HTTPError:
                result.error = "Crossref network request failed"
                break
            finally:
                self._next_request = self.clock() + 1.0
            if response.status_code != 200:
                result.error = f"Crossref HTTP {response.status_code}"
                break
            try:
                body = response.json()
                message = body["message"]
                items = message["items"]
                if body.get("status") != "ok" or not isinstance(items, list) or any(not isinstance(i, dict) for i in items):
                    raise ValueError("Unexpected metadata envelope")
            except (ValueError, KeyError, TypeError):
                result.error = "Invalid Crossref metadata response"
                break
            result.received += len(items)
            for item in items:
                paper = normalize_crossref(item, source)
                if paper is None:
                    result.filtered += 1
                else:
                    result.papers.append(paper)
            total = message.get("total-results")
            if len(items) < self.rows or (type(total) is int and result.received >= total):
                break
        result.status = ("partial" if result.received else "unavailable") if result.error else ("ok" if result.papers else "empty")
        return result

    def fetch_all(self, sources: list[Source], *, from_date: date) -> list[FetchResult]:
        # RSS-primary ECTA still has a supplementary Crossref result. BFI is disabled.
        return [self.fetch(source, from_date=from_date) for source in sources]
