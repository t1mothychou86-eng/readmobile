"""Reproduce the M4 sample from M2 recorded metadata, with no network access.

Run: aggregator/.venv/bin/python aggregator/scripts/make_feed_sample.py
Only the sample is written; runtime state and public feed are untouched.
"""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile

import httpx

from papercart.build import build_feed, write_feed
from papercart.network import Pacer
from papercart.privacy import PLACEHOLDER
from papercart.sources import load_sources
from papercart.state import State

ROOT = Path(__file__).resolve().parents[2]
FOLDER = ROOT / "aggregator/tests/fixtures/m2/build"
OUT = ROOT / "web/src/fixtures/feed.sample.json"
NOW = datetime(2026, 10, 12, 18, tzinfo=timezone.utc)


def make_sample():
    # A real local contact must never enter even mocked requests.
    os.environ["CROSSREF_MAILTO"] = PLACEHOLDER
    unused = json.loads((FOLDER / "manifest.json").read_text())

    def handler(request):
        params = {k: v for k, v in request.url.params.items() if k not in {"mailto", "api_key"}}
        match = next((r for r in unused if r["url"] == str(request.url.copy_with(query=None))
                      and r["method"] == request.method and r["params"] == params), None)
        if match is None:
            raise AssertionError("Request outside recorded metadata fixtures")
        unused.remove(match)
        file = FOLDER / match["fixture"]
        headers = dict(match["headers"])
        headers["content-type"] = "application/json" if file.suffix == ".json" else "application/rss+xml"
        return httpx.Response(match["status"], content=file.read_bytes(), headers=headers)

    with tempfile.TemporaryDirectory(prefix="papercart-sample-") as directory:
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            feed = build_feed(load_sources(), client=client, now=NOW, state=State(Path(directory) / "state.json"),
                              pacer=Pacer(sleep=lambda _: None, clock=lambda: 0), enrich=False)
    selected = []
    for source in feed["sources"]:
        own = [p for p in feed["papers"] if p["source"] == source["id"]]
        sample = own[:3]
        if source["id"] == "nber":
            # Both undated RSS and dated Crossref cases help exercise M4 display.
            sample = [p for p in own if not p["published"]][:2] + [p for p in own if p["published"]][:1]
        selected.extend(sample)
        source.update(count=len(sample), abstract_count=sum(bool(p["abstract"]) for p in sample))
    selected_ids = {p["id"] for p in selected}
    feed["papers"] = [p for p in feed["papers"] if p["id"] in selected_ids]
    return feed


if __name__ == "__main__":
    sample = make_sample()
    write_feed(sample, OUT)
    print(f"Offline sample: {len(sample['papers'])} papers, 12 active sources; BFI disabled")
