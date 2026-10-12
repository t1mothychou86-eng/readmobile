"""Build schema-1 static metadata feed. Zotero mapping remains an M3 task."""

import argparse
from collections import Counter
from datetime import date, datetime, timedelta, timezone
import calendar
import json
import logging
from pathlib import Path
import os
import re
import time
from urllib.parse import urlsplit

import httpx

from .crossref import CrossrefFetcher
from .dedupe import merge_papers
from .enrichment import AbstractEnricher
from .network import Pacer
from .normalize import Paper
from .privacy import redact_metadata, protect_http_logs
from .rss import RSSFetcher
from .schema import validate_feed
from .sources import load_sources
from .state import DEFAULT_STATE, State, timestamp

LOGGER = logging.getLogger(__name__)
LEGACY_CACHE = Path(__file__).resolve().parents[2] / ".cache/abstracts.json"


def in_window(published, start, today):
    if not published:
        return False
    try:
        parts = [int(v) for v in published.split("-")]
        first = date(parts[0], parts[1] if len(parts) > 1 else 1, parts[2] if len(parts) > 2 else 1)
        last = first if len(parts) == 3 else date(parts[0], parts[1], calendar.monthrange(parts[0], parts[1])[1]) if len(parts) == 2 else date(parts[0], 12, 31)
        return first <= today and last >= start
    except (TypeError, ValueError):
        return False


def backend_summary(result):
    return {key: getattr(result, key) for key in ("status", "pages", "received", "filtered", "error")}


def empty_enrichment():
    return {"pages": 0, "requested": 0, "matched": 0, "filled": 0, "cache_hits": 0, "deferred": 0, "error": None}


def migrate_previous(previous):
    """Upgrade the pre-E2 schema-1 artifact without inventing publication dates."""
    previous = redact_metadata(previous)
    for paper in previous["papers"]:
        paper.setdefault("first_seen", previous["generated_at"])
        paper.setdefault("date_precision", "published" if paper["published"] else "first_seen")
    for source in previous["sources"]:
        source["enrichment"].setdefault("deferred", 0)
    validate_feed(previous)
    return previous


def allowed_paper(paper, active):
    return paper.source in active and (paper.source != "ecb" or bool(re.search(r"/ecb\.wp[0-9]+", urlsplit(paper.url).path)))


def effective_date(paper):
    return paper.published or timestamp(paper.first_seen).date().isoformat()


def build_feed(sources, *, client, now, state, pacer=None, previous=None, enrich=True, abstract_max_requests=2, wall_clock=None):
    if now.tzinfo is None:
        raise ValueError("Build timestamp must have a timezone")
    today = now.date()
    start = today - timedelta(days=120)
    pacer = pacer or Pacer()
    cr = CrossrefFetcher(client, pacer=pacer, clock=pacer.clock, sleep=pacer.sleep)
    rss = RSSFetcher(client, pacer=pacer)
    all_papers, reports = [], []
    for source in sources:
        c = cr.fetch(source, from_date=start)
        r = rss.fetch(source)
        ordered = r.papers + c.papers if source.primary == "rss" or source.id == "nber" else c.papers + r.papers
        all_papers.extend(ordered)
        errors = [q.error for q in (c, r) if q.error]
        reports.append({"id": source.id, "name": source.name, "short": source.short, "group": source.group, "kind": source.kind,
                        "status": "disabled" if not source.active else "ok", "count": 0, "abstract_count": 0,
                        "excluded_date_count": 0, "errors": errors, "backends": {"crossref": backend_summary(c), "rss": backend_summary(r)},
                        "enrichment": empty_enrichment()})
        LOGGER.info("%s: Crossref %s (%d), RSS %s (%d)", source.id, c.status, len(c.papers), r.status, len(r.papers))
    if previous:
        previous = migrate_previous(previous)
        all_papers.extend(Paper(**item) for item in previous["papers"])
    all_papers.extend(state.history())
    active = {s.id for s in sources if s.active}
    all_papers = [p for p in all_papers if allowed_paper(p, active)]
    merged = merge_papers(all_papers)
    observed = [state.observe(p, now) for p in merged]
    # Remember even expired undated identities: deleting their first_seen would
    # resurrect an old RSS entry as "new" on its next appearance.
    state.remember(observed)
    excluded = Counter(p.source for p in observed if not in_window(effective_date(p), start, today))
    merged = [p for p in observed if in_window(effective_date(p), start, today)]
    if enrich:
        adapter = AbstractEnricher(client, state=state, now=now.timestamp(), pacer=pacer,
                                  max_requests=abstract_max_requests, clock=wall_clock)
        # NBER has priority; within it the latest papers are queried first.
        for sid in ("nber", "jpe"):
            report = next((r for r in reports if r["id"] == sid), None)
            if report is None:
                continue
            own = [p for p in merged if p.source == report["id"]]
            updated, stats = adapter.enrich(own)
            by_id = {p.id: p for p in updated}
            merged = [by_id.get(p.id, p) for p in merged]
            report["enrichment"] = stats
            if stats["error"]:
                report["errors"].append(stats["error"])
    state.remember(merged)
    merged.sort(key=lambda p: (effective_date(p), p.id), reverse=True)
    for report in reports:
        own = [p for p in merged if p.source == report["id"]]
        report.update(count=len(own), abstract_count=sum(bool(p.abstract) for p in own), excluded_date_count=excluded[report["id"]])
        if report["status"] != "disabled":
            successful = any(b["status"] in {"ok", "empty"} for b in report["backends"].values())
            report["status"] = "partial" if report["errors"] and (own or successful) else "unavailable" if report["errors"] else "ok" if own else "empty"
    feed = redact_metadata({"schema": 1, "generated_at": now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
                            "sources": reports, "papers": [p.to_dict() for p in merged]})
    validate_feed(feed)
    return feed


def write_feed(feed, out):
    validate_feed(feed)
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    temp = out.with_suffix(out.suffix + ".tmp")
    temp.write_text(json.dumps(redact_metadata(feed), ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temp.replace(out)


class Recorder:
    def __init__(self, folder):
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        self.counts, self.records = Counter(), []

    def __call__(self, response):
        response.read()
        url = response.request.url
        key = re.sub(r"[^a-zA-Z0-9.-]", "-", url.host + url.path)
        self.counts[key] += 1
        suffix = ".json" if "json" in response.headers.get("content-type", "") else ".xml"
        name = f"{key}-{self.counts[key]}{suffix}"
        text = response.text
        if suffix == ".json":
            try:
                data = response.json()
                if url.host == "api.crossref.org" and isinstance(data, dict):
                    # Recorded metadata projection; references/licenses/funders
                    # aren't consumed by M2 and can make responses many MB.
                    fields = {"DOI", "title", "type", "author", "abstract", "published", "published-online", "published-print", "issued", "prefix", "publisher", "container-title", "institution", "volume", "issue", "page", "article-number", "ISSN", "number", "URL", "resource"}
                    for item in data.get("message", {}).get("items", []):
                        for key in list(item):
                            if key not in fields:
                                item.pop(key)
                text = json.dumps(redact_metadata(data), ensure_ascii=False, indent=2)
            except ValueError:
                text = json.dumps({"error": "Non-JSON metadata response"})
        (self.folder / name).write_text(redact_metadata(text), encoding="utf-8")
        record = {"method": response.request.method, "url": str(url.copy_with(query=None)),
                  "params": {k: v for k, v in url.params.items() if k not in {"mailto", "api_key"}},
                  "status": response.status_code, "fixture": name,
                  "headers": {k: v for k, v in response.headers.items() if k.startswith("x-ratelimit") or k in {"retry-after", "backoff"}}}
        self.records.append(redact_metadata(record))
        (self.folder / "manifest.json").write_text(json.dumps(self.records, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--sources", type=Path)
    parser.add_argument("--no-enrich", action="store_true")
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--abstract-max-requests", type=int, default=2)
    parser.add_argument("--record-fixtures", type=Path)
    args = parser.parse_args()
    if args.record_fixtures and os.environ.get("LIVE_TEST") != "1":
        parser.error("Recording real network fixtures requires LIVE_TEST=1")
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    # httpx logs the raw mailto in URLs at INFO; redact and suppress its noise.
    protect_http_logs()
    logging.getLogger("httpx").setLevel(logging.WARNING)
    try:
        sources = load_sources(args.sources) if args.sources else load_sources()
        state = State(args.state)
        if args.abstract_max_requests < 0:
            raise ValueError("Abstract request budget must be nonnegative")
        migrated_cache = state.migrate_legacy_cache(LEGACY_CACHE) if args.state == DEFAULT_STATE else False
        previous = json.loads(args.out.read_text()) if args.out.exists() else None
        if previous:
            previous = migrate_previous(previous)
        recorder = Recorder(args.record_fixtures) if args.record_fixtures else None
        with httpx.Client(timeout=30, follow_redirects=False, headers={"User-Agent": "PaperCart/0.2 (metadata only)"},
                          event_hooks={"response": [recorder]} if recorder else {}) as client:
            feed = build_feed(sources, client=client, now=datetime.now(timezone.utc), previous=previous,
                              state=state, enrich=not args.no_enrich, abstract_max_requests=args.abstract_max_requests,
                              wall_clock=time.time)
        state.save()
        write_feed(feed, args.out)
        if migrated_cache:
            LEGACY_CACHE.unlink()
        for source in feed["sources"]:
            LOGGER.info("%s: %s, %d papers, %d abstracts%s", source["id"], source["status"], source["count"], source["abstract_count"],
                        "; " + "; ".join(source["errors"]) if source["errors"] else "")
        LOGGER.info("feed schema validated: %d papers", len(feed["papers"]))
    except (OSError, ValueError, TypeError):
        LOGGER.error("Build/config/schema failed; details omitted to protect private metadata")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
