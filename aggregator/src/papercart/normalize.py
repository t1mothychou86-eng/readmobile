"""Crossref metadata to the common Paper model; never dereference item URLs."""

from dataclasses import asdict, dataclass, field
from datetime import date
from html import unescape
from html.parser import HTMLParser
import re

from .privacy import redact_metadata
from .sources import Source


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        tag = tag.rsplit(":", 1)[-1]
        if tag in {"script", "style"}:
            self.hidden += 1
        if tag in {"p", "div", "br", "sec", "title", "li"} and not self.hidden:
            self.parts.append(" ")

    def handle_endtag(self, tag):
        tag = tag.rsplit(":", 1)[-1]
        if tag in {"script", "style"}:
            self.hidden = max(0, self.hidden - 1)
        if tag in {"p", "div", "sec", "title", "li"} and not self.hidden:
            self.parts.append(" ")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def plain_text(value) -> str:
    if not isinstance(value, str):
        return ""
    parser = _Text()
    parser.feed(unescape(value))
    parser.close()
    return " ".join("".join(parser.parts).split())


def normalize_doi(value) -> str | None:
    if not isinstance(value, str):
        return None
    doi = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", value.strip(), flags=re.I).lower()
    return doi if re.fullmatch(r"10\.[0-9]{4,9}/[^\s<>]+", doi) else None


def matches_series(source: Source, doi: str) -> bool:
    # Enforce D7 even if a future edit accidentally broadens the YAML pattern.
    if source.id == "nber" and not re.fullmatch(r"10\.3386/w[0-9]+", doi):
        return False
    if source.id == "feds" and not doi.startswith("10.17016/feds."):
        return False
    config = source.crossref
    return not (config and config.doi_pattern) or bool(re.match(config.doi_pattern, doi))


NON_PAPER = re.compile(
    r"^(?:front\s*matter|back\s*matter|table of contents|issue information|"
    r"editorial(?: report)?|editor(?:['’]s|s['’]) report|report (?:of|from) the editor|"
    r"announcements?|american finance association|(?:acknowledg(?:e)?ments?|thanks) to (?:reviewers|referees)|"
    r"(?:list of |acknowledg(?:e)?ments? (?:of |to )?)referees|"
    r"correction(?: to)?|erratum(?: to)?|corrigendum(?: to)?|retraction(?: of)?)"
    r"(?:$|\s*[:\-–—]|\s+(?:to|of|for|vol(?:ume)?\b|[0-9]{4}\b))", re.I
)


@dataclass(frozen=True)
class Paper:
    id: str
    doi: str
    source: str
    kind: str
    title: str
    authors: list[dict[str, str]]
    abstract: str | None
    published: str | None
    url: str
    wp_number: str | None = None
    publication_title: str | None = None
    journal_abbreviation: str | None = None
    volume: str | None = None
    issue: str | None = None
    pages: str | None = None
    issn: str | None = None
    institution: str | None = None
    series_title: str | None = None
    # M3 populates Zotero fields. M1 does not perform Zotero mapping.
    zotero: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def publication_date(item: dict) -> str | None:
    # Retain precision: a year-only deposit stays YYYY, not a fabricated Jan 1.
    for key in ("published", "published-online", "published-print", "issued"):
        data = item.get(key)
        parts = data.get("date-parts") if isinstance(data, dict) else None
        if not isinstance(parts, list) or not parts or not isinstance(parts[0], list):
            continue
        values = parts[0]
        if not 1 <= len(values) <= 3 or any(type(v) is not int for v in values):
            continue
        try:
            date(values[0], values[1] if len(values) > 1 else 1, values[2] if len(values) > 2 else 1)
        except ValueError:
            continue
        return "-".join(f"{v:04d}" if n == 0 else f"{v:02d}" for n, v in enumerate(values))
    return None


def _first(value) -> str:
    if isinstance(value, list):
        return next((plain_text(v) for v in value if plain_text(v)), "")
    return plain_text(value)


def normalize_crossref(item: dict, source: Source) -> Paper | None:
    if not source.active or not isinstance(item, dict):
        return None
    item = redact_metadata(item)
    doi = normalize_doi(item.get("DOI"))
    title = _first(item.get("title"))
    if not doi or not title or not matches_series(source, doi) or NON_PAPER.match(title):
        return None
    if source.kind == "journal" and item.get("type") != "journal-article":
        return None
    if source.kind == "working-paper" and (not isinstance(item.get("type"), str) or item["type"] not in {"report", "posted-content", "journal-article"}):
        return None
    authors = []
    raw_authors = item.get("author", [])
    for author in raw_authors if isinstance(raw_authors, list) else []:
        if isinstance(author, dict):
            given, family = plain_text(author.get("given")), plain_text(author.get("family")) or plain_text(author.get("name"))
            if given or family:
                authors.append({"given": given, "family": family})
    journal = source.kind == "journal"
    abstract = plain_text(item.get("abstract")) or None
    wp_number = None
    institution = None
    if not journal:
        if source.id == "nber":
            wp_number = doi.split("/w", 1)[1]
        elif source.id == "feds":
            wp_number = doi.split("/feds.", 1)[1]
        else:
            wp_number = _first(item.get("number")) or None
        institutions = item.get("institution", [])
        if isinstance(institutions, list):
            institution = next((plain_text(i.get("name")) for i in institutions if isinstance(i, dict) and plain_text(i.get("name"))), None)
        institution = institution or plain_text(item.get("publisher")) or source.name
    return Paper(
        id=f"doi:{doi}", doi=doi, source=source.id,
        kind="journalArticle" if journal else "report", title=title,
        authors=authors, abstract=abstract, published=publication_date(item),
        url=f"https://doi.org/{doi}", wp_number=wp_number,
        publication_title=_first(item.get("container-title")) or source.name if journal else None,
        journal_abbreviation=source.short if journal else None,
        volume=str(item["volume"]) if item.get("volume") is not None else None,
        issue=str(item["issue"]) if item.get("issue") is not None else None,
        pages=str(item.get("page") or item.get("article-number")) if item.get("page") or item.get("article-number") else None,
        issn=_first(item.get("ISSN")) or (source.crossref.issn if source.crossref else None) if journal else None,
        institution=institution, series_title=source.name if not journal else None,
    )
