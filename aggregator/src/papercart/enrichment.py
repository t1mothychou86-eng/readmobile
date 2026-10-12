"""Optional Semantic Scholar DOI abstract lookup, with cache and cooldown."""

from dataclasses import replace
import httpx

from .network import Pacer, retry_seconds
from .normalize import normalize_doi, plain_text
from .privacy import redact_metadata, protect_http_logs

ENDPOINT = "https://api.semanticscholar.org/graph/v1/paper/batch"


class AbstractEnricher:
    def __init__(self, client, *, state, now: float, pacer=None, max_requests=2, clock=None):
        protect_http_logs()
        if type(max_requests) is not int or max_requests < 0:
            raise ValueError("Abstract request budget must be a nonnegative integer")
        self.client, self.now = client, now
        self.clock = clock or (lambda: now)
        self.remaining = max_requests
        self.pacer = pacer or Pacer()
        self.cache = state.data["semantic_scholar"]

    def enrich(self, papers):
        report = {"pages": 0, "requested": 0, "matched": 0, "filled": 0, "cache_hits": 0, "deferred": 0, "error": None}
        def newest(p):
            # Partial publication dates preserve precision. Tie-break NBER's
            # same-month deposits by their measured working-paper number.
            number = int(p.wp_number) if p.wp_number and p.wp_number.isdigit() else 0
            return (p.published or p.first_seen or "", number, p.id)
        ordered = sorted(papers, key=newest, reverse=True)
        missing = list(dict.fromkeys(p.doi for p in ordered if p.doi and not p.abstract and p.source in {"jpe", "nber"}))
        abstracts, fresh = {}, []
        for doi in missing:
            cached = self.cache["entries"].get(doi)
            if isinstance(cached, dict) and (cached.get("abstract") or (type(cached.get("expires")) in (int, float) and cached["expires"] > self.clock())):
                report["cache_hits"] += 1
                if isinstance(cached.get("abstract"), str) and cached["abstract"].strip():
                    abstracts[doi] = cached["abstract"]
            else:
                fresh.append(doi)
        if fresh and self.cache.get("blocked_until", 0) > self.clock():
            report["error"] = "Semantic Scholar cooling down after a previous rate limit"
            report["deferred"] = len(fresh)
            fresh = []
        # <=500 IDs per batch, <=2 batches per source, AND a global run budget.
        for offset in range(0, min(len(fresh), 1000), 500):
            if not self.remaining:
                break
            batch = fresh[offset:offset+500]
            self.remaining -= 1
            report["pages"] += 1
            report["requested"] += len(batch)
            try:
                response = self.pacer.request(self.client, "POST", ENDPOINT,
                                             params={"fields": "externalIds,abstract,title"},
                                             json={"ids": ["DOI:" + d for d in batch]})
            except httpx.HTTPError:
                report["error"] = "Semantic Scholar metadata request failed or host cooling down"
                break
            if response.status_code != 200:
                report["error"] = f"Semantic Scholar HTTP {response.status_code}"
                if response.status_code in (429, 503):
                    # Budget/cooldown starts when the RESPONSE arrives, not when
                    # the slow multi-source build started.
                    self.cache["blocked_until"] = self.clock() + max(60, retry_seconds(response.headers))
                break
            try:
                data = redact_metadata(response.json())
                if not isinstance(data, list):
                    raise ValueError("Invalid batch")
            except ValueError:
                report["error"] = "Invalid Semantic Scholar metadata response"
                break
            found = {}
            for item in data:
                if not isinstance(item, dict) or not isinstance(item.get("externalIds"), dict):
                    continue
                doi = normalize_doi(item["externalIds"].get("DOI"))
                if doi not in batch:
                    continue
                report["matched"] += 1
                abstract = plain_text(item.get("abstract")) or None
                found[doi] = abstract
                if abstract:
                    abstracts[doi] = abstract
            for doi in batch:
                abstract = found.get(doi)
                self.cache["entries"][doi] = {"abstract": abstract, "expires": self.clock() + 86400}
        report["deferred"] = max(report["deferred"], len(fresh) - report["requested"])
        output = []
        for paper in papers:
            if not paper.abstract and paper.doi in abstracts:
                paper = replace(paper, abstract=abstracts[paper.doi])
                report["filled"] += 1
            output.append(paper)
        return output, report
