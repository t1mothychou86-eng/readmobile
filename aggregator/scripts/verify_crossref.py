"""Reproduce M1 probes; LIVE_TEST=1 is required. Metadata API only."""

import argparse
from datetime import date, datetime, timezone
import json
import os
from pathlib import Path
import sys
import time

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from papercart.crossref import CrossrefFetcher
from papercart.privacy import PLACEHOLDER, protect_http_logs, redact_metadata
from papercart.sources import load_sources

FIXTURES = Path(__file__).resolve().parents[1] / "tests/fixtures"


def save(name, value):
    (FIXTURES / name).write_text(json.dumps(redact_metadata(value), ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("ecta-metadata", "ecta-controls", "ecta-year-sample", "pagination", "prefixes"))
    args = parser.parse_args()
    if os.environ.get("LIVE_TEST") != "1":
        parser.error("Network verification requires LIVE_TEST=1")
    protect_http_logs()
    mailto = os.environ.get("CROSSREF_MAILTO") or PLACEHOLDER
    if mailto == PLACEHOLDER:
        print("WARNING: CROSSREF_MAILTO 未设置，使用 papercart@example.invalid")
    records = []
    if args.mode in {"pagination", "prefixes"}:
        sources = {s.id: s for s in load_sources()}
        source_ids = ["aer"] if args.mode == "pagination" else ["nber", "feds"]
        page_counts = {s: 0 for s in source_ids}

        def record(response):
            source = next(s for s in source_ids if (sources[s].crossref.issn or sources[s].crossref.prefix) in response.request.url.path)
            page_counts[source] += 1
            if response.status_code == 200:
                response.read()
                filename = f"crossref-m1-{source}-page-{page_counts[source]}.json"
                save(filename, response.json())

        with httpx.Client(timeout=40, follow_redirects=False, event_hooks={"response": [record]}) as client:
            with CrossrefFetcher(client=client, rows=2 if args.mode == "pagination" else 25,
                                 max_pages=2 if args.mode == "pagination" else 1) as api:
                for source_id in source_ids:
                    result = api.fetch(sources[source_id], from_date=date(2026, 6, 15))
                    record_summary = {"source": source_id, "status": result.status, "pages": result.pages,
                                      "received": result.received, "kept": len(result.papers), "filtered": result.filtered,
                                      "error": result.error, "checked_at": datetime.now(timezone.utc).isoformat()}
                    records.append(record_summary)
                    print(json.dumps(record_summary, ensure_ascii=False), flush=True)
    else:
        if args.mode == "ecta-metadata":
            queries = [("ecta-without-type", "/journals/0012-9682/works", {"filter": "from-pub-date:2026-06-15", "sort": "published", "order": "desc", "rows": 25}),
                       ("ecta-current-doi", "/works/10.3982%2FECTA23242", {})]
        elif args.mode == "ecta-year-sample":
            queries = [("ecta-year-sample", "/journals/0012-9682/works", {"filter": "from-pub-date:2026-01-01,type:journal-article", "sort": "published", "order": "desc", "rows": 25})]
        else:
            queries = [(f"ecta-date-control-{label}", "/works", {"filter": f"doi:10.3982/ecta23242,from-pub-date:{start},type:journal-article", "rows": 1})
                       for label, start in (("year-start", "2026-01-01"), ("window-start", "2026-06-15"))]
        with httpx.Client(timeout=40, follow_redirects=False) as client:
            for name, route, params in queries:  # At most two requests per run.
                record_summary = {"name": name, "route": route, "params": params, "checked_at": datetime.now(timezone.utc).isoformat()}
                try:
                    response = client.get("https://api.crossref.org" + route, params={**params, "mailto": mailto})
                    record_summary["status"] = response.status_code
                    if response.status_code == 200:
                        data = redact_metadata(response.json())
                        save(name + ".json", data)
                        items = data["message"].get("items", [data["message"]])
                        record_summary["count"] = len(items)
                        record_summary["total_results"] = data["message"].get("total-results")
                        record_summary["date_precision"] = [i.get("published", {}).get("date-parts") for i in items]
                    else:
                        record_summary["error"] = "Metadata API returned a non-200 status"
                except (httpx.HTTPError, ValueError, KeyError, TypeError):
                    record_summary["error"] = "Metadata probe failed; request details omitted"
                records.append(record_summary)
                print(json.dumps(record_summary, ensure_ascii=False), flush=True)
                time.sleep(1)
    save(f"spike-m1-{args.mode}.json", records)


if __name__ == "__main__":
    main()
