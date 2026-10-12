"""D2: probe a fixed recorded DOI sample using public metadata APIs only."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path

import httpx

from papercart.network import Pacer
from papercart.normalize import normalize_crossref
from papercart.privacy import redact_metadata, protect_http_logs
from papercart.sources import load_sources

FIXTURES = Path(__file__).resolve().parents[1] / "tests/fixtures"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("provider", choices=("openalex", "semantic-scholar"))
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    if os.environ.get("LIVE_TEST") != "1":
        parser.error("Real metadata probes require LIVE_TEST=1")
    protect_http_logs()
    args.out.mkdir(parents=True, exist_ok=True)
    sources = {s.id:s for s in load_sources()}
    pacer, records = Pacer(), []
    with httpx.Client(timeout=30, follow_redirects=False) as client:
        for sid in ("jpe", "jfe"):
            source = sources[sid]
            response = json.loads((FIXTURES / f"crossref-{sid}-{source.crossref.issn}.json").read_text())
            dois = [p.doi for item in response["message"]["items"] if (p:=normalize_crossref(item, source)) and not p.abstract]
            record = {"provider":args.provider,"source":sid,"requested":len(dois),"dois":dois,"checked_at":datetime.now(timezone.utc).isoformat()}
            try:
                if args.provider == "openalex":
                    url = "https://api.openalex.org/works"
                    result = pacer.request(client,"GET",url,params={"filter":"doi:"+"|".join("https://doi.org/"+d for d in dois),"per_page":100,"select":"doi,abstract_inverted_index,title"})
                else:
                    url = "https://api.semanticscholar.org/graph/v1/paper/batch"
                    result = pacer.request(client,"POST",url,params={"fields":"externalIds,abstract,title"},json={"ids":["DOI:"+d for d in dois]})
                record["status"] = result.status_code
                record["headers"] = {k:v for k,v in result.headers.items() if k.startswith("x-ratelimit") or k=="retry-after"}
                data = redact_metadata(result.json())
                (args.out/f"{args.provider}-{sid}.json").write_text(json.dumps(data,ensure_ascii=False,indent=2))
                if result.status_code==200:
                    items = data.get("results",[]) if args.provider=="openalex" else data
                    record["matched"] = sum(x is not None for x in items)
                    record["with_abstract"] = sum(bool(x and x.get("abstract_inverted_index" if args.provider=="openalex" else "abstract")) for x in items)
            except (httpx.HTTPError, ValueError, TypeError, AttributeError):
                record["error"] = "Metadata probe failed; details omitted"
            records.append(record)
            print(json.dumps(redact_metadata(record),ensure_ascii=False),flush=True)
            # A 429 is not coverage=0; don't query the same provider for the other source.
            if record.get("status") in (401,403,429,503) or record.get("error"):
                break
    (args.out/"summary.json").write_text(json.dumps(redact_metadata(records),ensure_ascii=False,indent=2))


if __name__=="__main__":
    main()
