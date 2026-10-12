"""Load verified source configuration; disabled entries remain discoverable."""

from dataclasses import dataclass
from datetime import date
from pathlib import Path
import re
from urllib.parse import urlsplit

import yaml

DEFAULT_CONFIG = Path(__file__).resolve().parents[2] / "sources.yaml"
STATUSES = {"passed", "limited", "disabled", "failed"}


@dataclass(frozen=True)
class CrossrefConfig:
    issn: str | None = None
    prefix: str | None = None
    doi_pattern: str | None = None

    def __post_init__(self):
        if bool(self.issn) == bool(self.prefix):
            raise ValueError("Select one verified ISSN or DOI prefix")
        if self.issn and not re.fullmatch(r"[0-9]{4}-[0-9]{3}[0-9X]", self.issn):
            raise ValueError("Invalid ISSN")
        if self.prefix and not re.fullmatch(r"10\.[0-9]{4,9}", self.prefix):
            raise ValueError("Invalid DOI prefix")
        if self.prefix and not self.doi_pattern:
            raise ValueError("Prefix needs a series pattern")
        if self.doi_pattern:
            re.compile(self.doi_pattern)


@dataclass(frozen=True)
class RSSConfig:
    url: str
    abstract_location: str | None

    def __post_init__(self):
        target = urlsplit(self.url)
        # Configured feed URLs are the only publisher URLs the program requests.
        # Validate even a "verified" config to guard against accidental PDF edits.
        if target.scheme != "https" or not target.hostname or target.username or target.password:
            raise ValueError("RSS needs a public HTTPS feed URL")
        if re.search(r"(?:\.pdf(?:$|[/?])|/(?:pdf|full|fulltext)(?:/|$))", target.path, re.I):
            raise ValueError("PDF/full-text URLs cannot be RSS endpoints")
        if not (re.search(r"(?:/rss(?:/|$)|/feed(?:/|$)|/showFeed$|\.(?:rss|xml)$)", target.path, re.I) or
                (target.hostname == "rss.sciencedirect.com" and re.fullmatch(r"/publication/science/[0-9X]+", target.path))):
            raise ValueError("RSS URL must identify a metadata feed")
        if self.abstract_location not in {None, "description", "content:encoded"}:
            raise ValueError("Unknown RSS abstract location")


@dataclass(frozen=True)
class Source:
    id: str
    name: str
    short: str
    group: str
    kind: str
    verified: str | None
    status: str
    primary: str
    crossref: CrossrefConfig | None = None
    rss: RSSConfig | None = None

    @property
    def active(self) -> bool:
        return self.status in {"passed", "limited"}


def load_sources(path: str | Path = DEFAULT_CONFIG) -> list[Source]:
    document = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(document, dict) or document.get("schema") != 1 or not isinstance(document.get("sources"), list):
        raise ValueError("Expected source configuration schema 1")
    sources = []
    seen = set()
    for entry in document["sources"]:
        if not isinstance(entry, dict):
            raise ValueError("Source entries must be mappings")
        source_id = entry.get("id", "")
        if not isinstance(source_id, str) or not re.fullmatch(r"[a-z0-9-]+", source_id) or source_id in seen:
            raise ValueError("Invalid or duplicate source id")
        seen.add(source_id)
        for field in ("name", "short", "group", "kind", "status", "verified"):
            if field not in entry:
                raise ValueError(f"Source {source_id}: missing {field}")
        if entry["status"] not in STATUSES:
            raise ValueError(f"Source {source_id}: invalid status")
        verified = entry["verified"]
        if verified is not None:
            verified = str(verified)
            date.fromisoformat(verified)
        if entry["status"] in {"passed", "limited"} and verified is None:
            raise ValueError(f"Source {source_id}: active source must be verified")
        if entry["kind"] not in {"journal", "working-paper"} or entry["group"] not in {"econ-top5", "finance", "working-paper"}:
            raise ValueError(f"Source {source_id}: invalid kind/group")
        config = None
        if "crossref" in entry:
            raw = entry["crossref"]
            if not isinstance(raw, dict) or not raw.get("verified"):
                raise ValueError(f"Source {source_id}: Crossref endpoint must be verified")
            issn, prefix, pattern = raw.get("issn"), raw.get("prefix"), raw.get("doi_pattern")
            config = CrossrefConfig(issn, prefix, pattern)
        primary = entry.get("primary", "crossref" if config else "rss")
        if primary not in {"crossref", "rss"}:
            raise ValueError(f"Source {source_id}: invalid primary")
        rss = None
        raw_rss = entry.get("rss")
        if isinstance(raw_rss, dict) and type(raw_rss.get("enabled", True)) is not bool:
            raise ValueError(f"Source {source_id}: RSS enabled must be boolean")
        if isinstance(raw_rss, dict) and raw_rss.get("enabled", True) and raw_rss.get("status") == "passed" and raw_rss.get("verified") and raw_rss.get("url"):
            rss = RSSConfig(raw_rss["url"], raw_rss.get("abstract_location"))
        sources.append(Source(source_id, entry["name"], entry["short"], entry["group"], entry["kind"], verified, entry["status"], primary, config, rss))
    return sources
