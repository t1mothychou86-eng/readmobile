"""Durable observation dates, paper metadata/abstracts and S2 lookup state."""

from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path

from .dedupe import normalize_url
from .normalize import Paper
from .privacy import redact_metadata

DEFAULT_STATE = Path(__file__).resolve().parents[2] / "state/state.json"


def timestamp(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("State timestamps require a timezone")
    return parsed.astimezone(timezone.utc)


class State:
    def __init__(self, path):
        self.path = Path(path)
        self.existed = self.path.exists()
        if self.existed:
            self.data = redact_metadata(json.loads(self.path.read_text(encoding="utf-8")))
        else:
            self.data = {"schema": 1, "papers": {}, "semantic_scholar": {"entries": {}, "blocked_until": 0}}
        if not isinstance(self.data, dict) or self.data.get("schema") != 1 or not isinstance(self.data.get("papers"), dict):
            raise ValueError("Invalid state schema")
        s2 = self.data.get("semantic_scholar")
        if not isinstance(s2, dict) or not isinstance(s2.get("entries"), dict) or type(s2.get("blocked_until")) not in (int, float):
            raise ValueError("Invalid Semantic Scholar state")
        self.url_ids = {}
        for identity, record in self.data["papers"].items():
            if (not isinstance(record, dict) or not isinstance(record.get("paper"), dict) or
                    record["paper"].get("id") != identity or not isinstance(record.get("first_seen"), str) or
                    not isinstance(record["paper"].get("url"), str) or not isinstance(record.get("aliases", []), list)):
                raise ValueError("Invalid paper state")
            timestamp(record["first_seen"])
            for url in [record["paper"]["url"], *record.get("aliases", [])]:
                if (key := normalize_url(url)):
                    self.url_ids.setdefault(key, []).append(identity)

    def history(self):
        return [Paper(**record["paper"], aliases=record.get("aliases", [])) for record in self.data["papers"].values()]

    def observe(self, paper, now):
        records = self.data["papers"]
        old = records.get(paper.id)
        if not old:
            for url in [paper.url, *paper.aliases]:
                candidates = [records[i] for i in self.url_ids.get(normalize_url(url), [])]
                old = next((r for r in candidates if r["paper"]["source"] == paper.source and
                            (not paper.doi or not r["paper"].get("doi") or r["paper"]["doi"] == paper.doi)), None)
                if old:
                    break
        candidates = [now.isoformat(), *( [paper.first_seen] if paper.first_seen else []), *([old["first_seen"]] if old else [])]
        first_seen = min(candidates, key=timestamp)
        abstract = paper.abstract or (old["paper"].get("abstract") if old else None)
        return replace(paper, first_seen=timestamp(first_seen).isoformat().replace("+00:00", "Z"),
                       date_precision="published" if paper.published else "first_seen", abstract=abstract)

    def remember(self, papers):
        for paper in papers:
            self.data["papers"][paper.id] = {"first_seen": paper.first_seen, "paper": paper.to_dict(), "aliases": paper.aliases}

    def migrate_legacy_cache(self, path):
        """One-time import; never write or continue using the old cache file."""
        path = Path(path)
        if self.existed or not path.exists():
            return False
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("schema") != 1 or not isinstance(data.get("entries"), dict) or type(data.get("blocked_until")) not in (int, float):
            raise ValueError("Invalid legacy cache")
        self.data["semantic_scholar"] = redact_metadata({"entries": data["entries"], "blocked_until": data["blocked_until"]})
        return True

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(self.path.suffix + ".tmp")
        temp.write_text(json.dumps(redact_metadata(self.data), ensure_ascii=False, indent=2, allow_nan=False)+"\n", encoding="utf-8")
        temp.replace(self.path)
