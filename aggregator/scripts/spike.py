"""M0-only metadata probes. No Zotero writes; opt in with LIVE_TEST=1.

Candidates are hypotheses, not verified runtime configuration. Results and
sanitized response fixtures are saved for manual review in docs/SPIKES.md.
"""

import argparse
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import json
import os
from pathlib import Path
import re
import subprocess
import time

import feedparser
import httpx

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "aggregator/tests/fixtures"
EMAIL = re.compile(r"[\w.%+\-]+@[\w.\-]+\.[a-zA-Z]{2,}")
ORIGIN = "https://example.github.io"
JOURNALS = {
    "aer": ("0002-8282", "1944-7981"),
    "qje": ("0033-5533", "1531-4650"),
    "jpe": ("0022-3808", "1537-534X"),
    "ecta": ("0012-9682", "1468-0262"),
    "res": ("0034-6527", "1467-937X"),
    "jf": ("0022-1082", "1540-6261"),
    "jfe": ("0304-405X", "1879-2773"),
    "rfs": ("0893-9454", "1465-7368"),
}
RSS = {
    "aer": "https://www.aeaweb.org/journals/aer/rss",
    "qje": "https://academic.oup.com/rss/site_5504/3365.xml",
    "jpe": "https://www.journals.uchicago.edu/action/showFeed?type=etoc&feed=rss&jc=jpe",
    "ecta": "https://onlinelibrary.wiley.com/feed/14680262/most-recent",
    "res": "https://academic.oup.com/rss/site_5508/3369.xml",
    "jf": "https://onlinelibrary.wiley.com/feed/15406261/most-recent",
    "jfe": "https://rss.sciencedirect.com/publication/science/0304405X",
    "rfs": "https://academic.oup.com/rss/site_5511/3372.xml",
    "nber": "https://back.nber.org/rss/new.xml",
    "feds": "https://www.federalreserve.gov/feeds/feds.xml",
    "ecb": "https://www.ecb.europa.eu/rss/wppub.html",
    "bis": "https://www.bis.org/doclist/wppubls.rss",
    "bfi": "https://bfi.uchicago.edu/feed/?post_type=working-paper",
}


def clean(value):
    return EMAIL.sub("papercart@example.invalid", value)


def save(name, value):
    if name == "rss-bfi.xml":
        # This candidate is a generic news feed, not working-paper metadata.
        # Retain discovery metadata only, never its complete news post bodies.
        value = re.sub(r"<content:encoded\b[^>]*>.*?</content:encoded>", "", value, flags=re.S)
    (FIXTURES / name).write_text(clean(value), encoding="utf-8")


def wait_headers(headers):
    delays = [1.0]
    for name in ("backoff", "retry-after"):
        value = headers.get(name)
        if value:
            try:
                delays.append(float(value))
            except ValueError:
                delays.append(max(0, (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds()))
    time.sleep(max(delays))


def probe(client, name, url, params=None):
    record = {"checked_at": datetime.now(timezone.utc).isoformat(), "url": url}
    try:
        # Follow at most one redirect, with the same one-second request spacing.
        response = client.get(url, params=params)
        if response.is_redirect:
            record["redirect"] = response.headers.get("location")
            wait_headers(response.headers)
            target = response.url.join(response.headers["location"])
            if target.path.lower().endswith(".pdf"):
                raise ValueError("Refusing PDF redirect")
            response = client.get(target)
        record.update(status=response.status_code, headers={
            k: v for k, v in response.headers.items()
            if k.startswith("access-control-") or k in ("content-type", "date", "backoff", "retry-after")
        })
        wait_headers(response.headers)
        if response.status_code == 200 and "application/pdf" not in response.headers.get("content-type", ""):
            save(name, response.text)
            record["fixture"] = name
            return record, response.text
        if "application/json" in response.headers.get("content-type", ""):
            record["error_response"] = clean(response.text[:2000])
        return record, ""
    except (httpx.HTTPError, ValueError) as exc:
        record["error"] = type(exc).__name__
        time.sleep(1)
        return record, ""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("section", choices=("crossref", "rss", "zotero"))
    args = parser.parse_args()
    if os.environ.get("LIVE_TEST") != "1":
        parser.error("Network probes require LIVE_TEST=1")
    mailto = os.environ.get("CROSSREF_MAILTO") or "papercart@example.invalid"
    if "CROSSREF_MAILTO" not in os.environ:
        print("WARNING: CROSSREF_MAILTO 未设置，使用 papercart@example.invalid", flush=True)
    FIXTURES.mkdir(parents=True, exist_ok=True)
    results = {}
    with httpx.Client(timeout=30, headers={"User-Agent": "PaperCart-M0/0.0", "Origin": ORIGIN}) as client:
        if args.section == "crossref":
            for source, issns in JOURNALS.items():
                for issn in issns:  # Two single-page queries per journal; no pagination.
                    name = f"crossref-{source}-{issn}.json"
                    record, body = probe(client, name, f"https://api.crossref.org/journals/{issn}/works", {
                        "filter": "from-pub-date:2026-06-15,type:journal-article",
                        "sort": "published", "order": "desc", "rows": 25, "mailto": mailto,
                        "select": "DOI,title,type,ISSN,container-title,abstract,published,prefix,publisher,author",
                    })
                    if body:
                        items = json.loads(body)["message"]["items"]
                        record.update(count=len(items), abstracts=sum(bool(i.get("abstract", "").strip()) for i in items),
                                      journals=sorted({t for i in items for t in i.get("container-title", [])}),
                                      issns=sorted({v for i in items for v in i.get("ISSN", [])}))
                    results[f"{source}:{issn}"] = record
                    print(source, issn, record.get("status"), record.get("count"), record.get("abstracts"), flush=True)
            for source, prefix in (("nber", "10.3386"), ("feds", "10.17016")):
                record, body = probe(client, f"crossref-{source}.json", f"https://api.crossref.org/prefixes/{prefix}/works", {
                    "filter": "from-pub-date:2026-06-15", "sort": "published", "order": "desc", "rows": 25,
                    "mailto": mailto,
                })
                if body:
                    items = json.loads(body)["message"]["items"]
                    record.update(count=len(items), dois=[i["DOI"] for i in items],
                                  publishers=sorted({i.get("publisher", "") for i in items}))
                results[source] = record
                print(source, record.get("status"), record.get("count"), flush=True)
        elif args.section == "rss":
            for source, url in RSS.items():
                record, body = probe(client, f"rss-{source}.xml", url)
                if body:
                    feed = feedparser.parse(body)
                    record.update(count=len(feed.entries), feed_title=feed.feed.get("title"),
                                  summaries=sum(bool(e.get("summary", "").strip()) for e in feed.entries),
                                  valid=bool(feed.version and feed.entries and not feed.bozo),
                                  entry_titles=[e.get("title", "") for e in feed.entries[:3]],
                                  sample_links=[e.get("link", "") for e in feed.entries[:3]])
                results[source] = record
                print(source, record.get("status"), record.get("count"), record.get("valid"), flush=True)
        else:
            for name, url, method, headers in (
                ("items", "https://api.zotero.org/users/0/items", "POST", "zotero-api-key,zotero-api-version,zotero-write-token,content-type"),
                ("keys", "https://api.zotero.org/keys/current", "GET", "zotero-api-key,zotero-api-version"),
            ):
                response = subprocess.run(["curl", "-sS", "-i", "-X", "OPTIONS", url, "--max-time", "30",
                    "-H", f"Origin: {ORIGIN}", "-H", f"Access-Control-Request-Method: {method}",
                    "-H", f"Access-Control-Request-Headers: {headers}"], check=True, capture_output=True, text=True)
                save(f"zotero-options-{name}.txt", response.stdout)
                # Parse response headers for server-requested pauses.
                parsed_headers = dict(re.findall(r"^([\w-]+):\s*(.*?)$", response.stdout.lower(), re.M))
                wait_headers(parsed_headers)
            for item_type in ("journalArticle", "report"):
                record, body = probe(client, f"zotero-{item_type}.json", "https://api.zotero.org/items/new", {"itemType": item_type})
                if body:
                    record["itemType"] = json.loads(body).get("itemType")
                results[item_type] = record
                print(item_type, record.get("status"), record.get("itemType"), flush=True)
    save(f"spike-{args.section}.json", json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
