"""Fetch configured RSS/Atom metadata once; item links are never requested."""

from datetime import datetime
from email.utils import parsedate_to_datetime
import re
from urllib.parse import urlsplit

import feedparser
import httpx

from .crossref import FetchResult
from .dedupe import normalize_url
from .network import Pacer
from .normalize import Paper, NON_PAPER, normalize_doi, plain_text, matches_series
from .privacy import redact, protect_http_logs


def entry_date(entry) -> str | None:
    for key in ("prism_coverdate", "cb_publicationdate", "published", "updated"):
        value = entry.get(key)
        if not isinstance(value, str):
            continue
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).date().isoformat()
        except ValueError:
            pass
        try:
            return parsedate_to_datetime(value).date().isoformat()
        except (ValueError, TypeError, OverflowError):
            pass
        for fmt in ("%d %b %Y", "%B %Y"):
            try:
                parsed = datetime.strptime(value, fmt)
                return parsed.strftime("%Y-%m" if fmt == "%B %Y" else "%Y-%m-%d")
            except ValueError:
                pass
    # ScienceDirect supplies publication month in description, not pubDate.
    match = re.search(r"Publication date:\s*([A-Za-z]+ [0-9]{4})", plain_text(entry.get("summary")))
    if match:
        try:
            return datetime.strptime(match[1], "%B %Y").strftime("%Y-%m")
        except ValueError:
            pass
    return None


def entry_doi(entry, source) -> str | None:
    for key in ("prism_doi", "dc_identifier", "id"):
        doi = normalize_doi(entry.get(key))
        if doi:
            return doi
    # NBER's verified /papers/w<number> identifiers map to the measured D7 series.
    if source.id == "nber":
        u = urlsplit(entry.get("link", ""))
        match = re.fullmatch(r"/papers/(w[0-9]+)", u.path)
        if u.hostname in {"www.nber.org", "nber.org"} and match:
            return "10.3386/" + match[1]
    link = entry.get("link", "")
    u = urlsplit(link)
    if u.hostname in {"doi.org", "dx.doi.org"}:
        return normalize_doi(link)
    return None


def normalize_entry(entry, source) -> Paper | None:
    title = plain_text(entry.get("title"))
    section = plain_text(entry.get("prism_section"))
    if not title or NON_PAPER.match(title) or re.search(r"(?:front matter|back matter|issue information|announcement|miscellaneous)", section, re.I):
        return None
    link = redact(entry.get("link", ""))
    url = normalize_url(link)
    if not url:
        return None
    doi = entry_doi(entry, source)
    if doi and not matches_series(source, doi):
        return None
    journal = source.kind == "journal"
    abstract = None
    if source.rss.abstract_location == "description":
        value = entry.get("summary", "")
        if source.id == "feds":
            value = re.split(r"<br\s*/?>\s*<br\s*/?>", value, maxsplit=1, flags=re.I)[-1]
        abstract = plain_text(value) or None
    elif source.rss.abstract_location == "content:encoded":
        abstract = plain_text(" ".join(v.get("value", "") for v in entry.get("content", []) if isinstance(v, dict))) or None
    if abstract:
        abstract = re.sub(r"^ABSTRACT\s+", "", abstract, flags=re.I)
        abstract = redact(abstract)
    authors = []
    if source.id == "nber" and " -- by " in title:
        title, author_text = title.split(" -- by ", 1)
        names = author_text.split(", ")
    elif source.id == "jpe":
        # This feed concatenates authors and affiliations without separators.
        # Don't fabricate a person from that string; Crossref fills creators.
        names = []
    else:
        names = [name for a in entry.get("authors", []) for name in re.split(r",\s*\n|\n", a.get("name", ""))]
    for name in names:
        name = plain_text(name)
        if name:
            given, _, family = name.rpartition(" ")
            authors.append({"given": given, "family": family or name})
    number = None
    if source.id == "nber" and doi:
        number = doi.split("/w")[1]
    elif source.id == "bis":
        number = entry.get("cb_issue")
    elif source.id == "ecb":
        match = re.search(r"ecb\.wp([0-9]+)", url)
        if not match:
            return None  # E1: Discussion Papers and other series are outside ECB WP.
        number = match[1]
    pages = None
    if entry.get("prism_startingpage"):
        pages = entry["prism_startingpage"] + ("-" + entry["prism_endingpage"] if entry.get("prism_endingpage") else "")
    return Paper(id=f"doi:{doi}" if doi else f"url:{url}", doi=doi, source=source.id,
                 kind="journalArticle" if journal else "report", title=redact(title), authors=authors,
                 abstract=abstract, published=entry_date(entry), url=f"https://doi.org/{doi}" if doi else url,
                 wp_number=number, publication_title=source.name if journal else None,
                 journal_abbreviation=source.short if journal else None,
                 volume=entry.get("prism_volume"), issue=entry.get("prism_number"), pages=pages,
                 issn=source.crossref.issn if journal and source.crossref else None,
                 institution=source.name if not journal else None, series_title=source.name if not journal else None,
                 aliases=[url])


class RSSFetcher:
    def __init__(self, client=None, *, pacer=None):
        protect_http_logs()
        self.client = client or httpx.Client(timeout=30, follow_redirects=False)
        self.owned = client is None
        self.pacer = pacer or Pacer()

    def close(self):
        if self.owned:
            self.client.close()

    def fetch(self, source) -> FetchResult:
        if not source.active:
            return FetchResult(source.id, "disabled")
        if source.rss is None:
            return FetchResult(source.id, "not_applicable")
        result = FetchResult(source.id, "empty", pages=1)
        try:
            response = self.pacer.request(self.client, "GET", source.rss.url)
        except httpx.HTTPError:
            result.status, result.error = "unavailable", "RSS metadata request failed or host cooling down"
            return result
        if response.status_code != 200:
            result.status, result.error = "unavailable", f"RSS HTTP {response.status_code}"
            return result
        # parse bytes, not a URL: feedparser cannot fetch item links.
        feed = feedparser.parse(redact(response.text).encode("utf-8"))
        if not feed.version or feed.bozo:
            result.status, result.error = "unavailable", "Invalid RSS/Atom metadata response"
            return result
        result.received = len(feed.entries)
        for entry in feed.entries:
            paper = normalize_entry(entry, source)
            if paper:
                result.papers.append(paper)
            else:
                result.filtered += 1
        result.status = "ok" if result.papers else "empty"
        return result
