from dataclasses import replace
import json

import httpx
import pytest
import respx

from papercart.enrichment import AbstractEnricher, ENDPOINT
from papercart.network import Pacer
from papercart.normalize import normalize_crossref
from papercart.state import State


@pytest.fixture
def papers(sources, fixture_json):
    return [q for item in fixture_json("crossref-jpe-0022-3808.json")["message"]["items"] if (q := normalize_crossref(item, sources["jpe"]))]


@respx.mock
def test_true_d2_batch_and_cache(papers, fixture_json, tmp_path):
    data = fixture_json("m2/d2-semantic-scholar-jpe.json")
    route = respx.post(ENDPOINT).respond(200, json=data)
    with httpx.Client() as client:
        adapter = AbstractEnricher(client, state=State(tmp_path/"state.json"), now=1000, pacer=Pacer(sleep=lambda _:None, clock=lambda:0))
        output, report = adapter.enrich(papers)
        assert report["requested"] == 22 and report["matched"] == 15 and report["filled"] == 4
        assert sum(bool(p.abstract) for p in output) == 4
        output2, report2 = adapter.enrich(papers)
        assert report2["cache_hits"] == 22 and report2["filled"] == 4 and route.call_count == 1
        assert [p.abstract for p in output2] == [p.abstract for p in output]


@respx.mock
def test_mismatched_doi_not_borrowed(papers, tmp_path):
    respx.post(ENDPOINT).respond(200, json=[{"externalIds":{"DOI":"10.1111/other"}, "abstract":"Wrong paper", "title":papers[0].title}])
    with httpx.Client() as client:
        out, stats = AbstractEnricher(client, state=State(tmp_path/"state.json"), now=0).enrich(papers[:1])
    assert out[0].abstract is None and stats["filled"] == 0


@respx.mock
def test_rate_limit_persists_and_keeps_other_data(papers, tmp_path):
    route = respx.post(ENDPOINT).respond(429, headers={"Retry-After":"3600"})
    path = tmp_path/"state.json"
    state = State(path)
    with httpx.Client() as client:
        out, stats = AbstractEnricher(client, state=state, now=100).enrich(papers)
        assert stats["error"] == "Semantic Scholar HTTP 429" and out == papers
        state.save()
        out, stats = AbstractEnricher(client, state=State(path), now=101).enrich(papers)
        assert stats["requested"] == 0 and "cooling down" in stats["error"] and route.call_count == 1
    assert json.loads(path.read_text())["semantic_scholar"]["blocked_until"] == 3700


@respx.mock
def test_existing_abstract_never_overwritten(papers, tmp_path):
    existing = replace(papers[0], abstract="Existing")
    with httpx.Client() as client:
        out, stats = AbstractEnricher(client, state=State(tmp_path/"state.json"), now=0).enrich([existing])
    assert out == [existing] and stats["requested"] == 0 and len(respx.calls) == 0


@respx.mock
def test_newest_nber_first_and_global_budget(papers, sources, fixture_json, tmp_path):
    sample = normalize_crossref(fixture_json("crossref-nber.json")["message"]["items"][0], sources["nber"])
    nber = [replace(sample, doi=f"10.3386/w{30000+n}", id=f"doi:10.3386/w{30000+n}", wp_number=str(30000+n),
                    published="2026-10", abstract=None) for n in range(600)]
    route = respx.post(ENDPOINT).respond(200, json=[])
    with httpx.Client() as client:
        adapter = AbstractEnricher(client, state=State(tmp_path/"state.json"), now=0, max_requests=1)
        _, report = adapter.enrich(nber)
        assert report["pages"] == 1 and report["requested"] == 500 and report["deferred"] == 100
        _, report2 = adapter.enrich(papers)
        assert report2["requested"] == 0 and report2["deferred"] == 22
    ids = json.loads(route.calls[0].request.content)["ids"]
    assert ids[0] == "DOI:10.3386/w30599" and ids[-1] == "DOI:10.3386/w30100"
    assert route.call_count == 1


@respx.mock
def test_cooldown_starts_after_response_not_build_start(papers, tmp_path):
    wall = [100]
    def late_response(request):
        wall[0] = 1000
        return httpx.Response(429, headers={"Retry-After":"120"})
    respx.post(ENDPOINT).mock(side_effect=late_response)
    state = State(tmp_path/"state.json")
    with httpx.Client() as client:
        AbstractEnricher(client, state=state, now=100, clock=lambda:wall[0]).enrich(papers)
    assert state.data["semantic_scholar"]["blocked_until"] == 1120


@respx.mock
def test_e5_jfe_is_not_queried(papers, tmp_path):
    paper = replace(papers[0], source="jfe")
    with httpx.Client() as client:
        _, report = AbstractEnricher(client, state=State(tmp_path/"state.json"), now=0).enrich([paper])
    assert report["requested"] == 0 and len(respx.calls) == 0


@respx.mock
def test_positive_and_negative_cache_reused_across_processes(papers, fixture_json, tmp_path):
    path=tmp_path/'state.json';state=State(path)
    route=respx.post(ENDPOINT).respond(200,json=fixture_json('m2/d2-semantic-scholar-jpe.json'))
    with httpx.Client() as client:
        AbstractEnricher(client,state=state,now=1000).enrich(papers)
        state.save()
        out,stats=AbstractEnricher(client,state=State(path),now=1001).enrich(papers)
    assert stats['cache_hits']==22 and stats['requested']==0 and route.call_count==1
    assert sum(bool(p.abstract) for p in out)==4
