from copy import deepcopy
from datetime import date
import json
import logging

import httpx
import pytest
import respx

from papercart.crossref import CrossrefFetcher
from papercart.privacy import PLACEHOLDER, redact, redact_metadata

START = date(2026, 6, 15)
JOURNAL = "https://api.crossref.org/journals/0002-8282/works"


class Time:
    def __init__(self):
        self.now = 0.0
        self.delays = []

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.delays.append(seconds)
        self.now += seconds


@pytest.fixture
def timer():
    return Time()


def fetcher(timer, **kwargs):
    return CrossrefFetcher(clock=timer.clock, sleep=timer.sleep, **kwargs)


@respx.mock
def test_two_recorded_pages_and_spacing(sources, fixture_json, timer):
    responses = [fixture_json(f"crossref-m1-aer-page-{n}.json") for n in (1, 2)]
    route = respx.get(JOURNAL).mock(side_effect=[httpx.Response(200, json=b) for b in responses])
    with fetcher(timer, rows=2) as api:
        result = api.fetch(sources["aer"], from_date=START)
    assert result.status == "ok" and result.pages == 2 and result.received == 4
    assert [p.doi for p in result.papers] == [i["DOI"].lower() for b in responses for i in b["message"]["items"]]
    assert route.call_count == 2 and timer.delays == [1.0]
    assert [call.request.url.params["offset"] for call in route.calls] == ["0", "2"]
    params = route.calls[0].request.url.params
    assert params["filter"] == "from-pub-date:2026-06-15,type:journal-article"
    assert params["sort"] == "published" and params["mailto"] == PLACEHOLDER


@respx.mock
def test_empty_ecta_is_not_network_failure(sources, fixture_json, timer):
    route = respx.get("https://api.crossref.org/journals/0012-9682/works").respond(200, json=fixture_json("crossref-ecta-0012-9682.json"))
    with fetcher(timer) as api:
        result = api.fetch(sources["ecta"], from_date=START)
    assert result.status == "empty" and result.error is None and result.papers == []
    assert result.pages == 1 and route.call_count == 1
    assert sources["ecta"].primary == "rss"  # supplementary request remains possible


@respx.mock
@pytest.mark.parametrize("source,fixture,count", [("nber", "crossref-nber.json", 25), ("feds", "crossref-feds.json", 10)])
def test_prefix_series_and_parameters(source, fixture, count, sources, fixture_json, timer):
    prefix = sources[source].crossref.prefix
    route = respx.get(f"https://api.crossref.org/prefixes/{prefix}/works").respond(200, json=fixture_json(fixture))
    with fetcher(timer) as api:
        result = api.fetch(sources[source], from_date=START)
    assert len(result.papers) == count and result.received == 25
    assert result.filtered == 25-count
    assert route.calls[0].request.url.params["filter"] == "from-pub-date:2026-06-15"
    assert "type:" not in route.calls[0].request.url.params["filter"]


@respx.mock
def test_disabled_and_rss_only_never_requested(sources, timer):
    with fetcher(timer) as api:
        assert api.fetch(sources["bfi"], from_date=START).status == "disabled"
        assert api.fetch(sources["ecb"], from_date=START).status == "not_applicable"
    assert len(respx.calls) == 0


@respx.mock
def test_short_page_stops(sources, fixture_json, timer):
    body = fixture_json("crossref-m1-aer-page-1.json")
    route = respx.get(JOURNAL).respond(200, json=body)
    with fetcher(timer, rows=3) as api:
        result = api.fetch(sources["aer"], from_date=START)
    assert result.pages == 1 and route.call_count == 1


@respx.mock
def test_total_count_stops_full_page(sources, fixture_json, timer):
    body = fixture_json("crossref-m1-aer-page-1.json")
    body["message"]["total-results"] = 2
    route = respx.get(JOURNAL).respond(200, json=body)
    with fetcher(timer, rows=2) as api:
        result = api.fetch(sources["aer"], from_date=START)
    assert result.pages == 1 and route.call_count == 1


@respx.mock
def test_failure_isolation_and_global_spacing(sources, fixture_json, timer):
    respx.get(JOURNAL).respond(503)
    respx.get("https://api.crossref.org/prefixes/10.3386/works").respond(200, json=fixture_json("crossref-nber.json"))
    with fetcher(timer) as api:
        results = api.fetch_all([sources["aer"], sources["nber"]], from_date=START)
    assert [r.status for r in results] == ["unavailable", "ok"]
    assert results[0].error == "Crossref HTTP 503" and timer.delays == [1.0]


@respx.mock
def test_second_page_failure_preserves_first_page(sources, fixture_json, timer):
    respx.get(JOURNAL).mock(side_effect=[httpx.Response(200, json=fixture_json("crossref-m1-aer-page-1.json")), httpx.Response(429)])
    with fetcher(timer, rows=2) as api:
        result = api.fetch(sources["aer"], from_date=START)
    assert result.status == "partial" and len(result.papers) == 2 and result.pages == 2


@respx.mock
def test_no_redirects_to_pdf_or_fulltext(sources, timer):
    respx.get(JOURNAL).respond(302, headers={"Location": "https://example.invalid/article/full/paper.pdf"})
    # An injected client's default redirect setting must not bypass the red line.
    with httpx.Client(follow_redirects=True) as client, fetcher(timer, client=client) as api:
        result = api.fetch(sources["aer"], from_date=START)
    assert result.status == "unavailable" and len(respx.calls) == 1


@respx.mock
def test_resource_and_pdf_links_are_not_requested(sources, fixture_json, timer):
    body = fixture_json("crossref-m1-aer-page-1.json")
    for item in body["message"]["items"]:
        item["link"] = [{"URL": "https://example.invalid/paper.pdf"}]
        item["resource"] = {"primary": {"URL": "https://example.invalid/article/full"}}
    respx.get(JOURNAL).respond(200, json=body)
    with fetcher(timer) as api:
        result = api.fetch(sources["aer"], from_date=START)
    assert result.status == "ok" and len(respx.calls) == 1
    assert all(p.url.startswith("https://doi.org/") for p in result.papers)


@respx.mock
@pytest.mark.parametrize("body", [{}, {"status": "ok", "message": {"items": "bad"}}, {"status": "ok", "message": {"items": [None]}}])
def test_invalid_envelope_is_reported(body, sources, timer):
    respx.get(JOURNAL).respond(200, json=body)
    with fetcher(timer) as api:
        result = api.fetch(sources["aer"], from_date=START)
    assert result.status == "unavailable" and result.error == "Invalid Crossref metadata response"


@respx.mock
def test_non_json_is_reported(sources, timer):
    respx.get(JOURNAL).respond(200, text="not json")
    with fetcher(timer) as api:
        assert api.fetch(sources["aer"], from_date=START).status == "unavailable"


@respx.mock
def test_contact_not_in_errors_or_httpx_logs(monkeypatch, caplog, sources, fixture_json, timer):
    contact = "private" + "@" + "example.invalid"
    monkeypatch.setenv("CROSSREF_MAILTO", contact)
    body = fixture_json("crossref-m1-aer-page-1.json")
    respx.get(JOURNAL).respond(200, json=body)
    caplog.set_level(logging.INFO, logger="httpx")
    with fetcher(timer) as api:
        result = api.fetch(sources["aer"], from_date=START)
    assert contact not in caplog.text and "private%40" not in caplog.text
    assert PLACEHOLDER in caplog.text and result.status == "ok"
    respx.get(JOURNAL).mock(side_effect=httpx.ConnectError(contact))
    with fetcher(timer) as api:
        result = api.fetch(sources["aer"], from_date=START)
    assert result.error == "Crossref network request failed"
    assert contact not in result.error


def test_recording_redacts_nested_values_and_encoded_contact(monkeypatch):
    contact = "private" + "@" + "example.invalid"
    monkeypatch.setenv("CROSSREF_MAILTO", contact)
    raw = {"url": "https://example.invalid/?mailto=private%40example.invalid", "author": [{"email": contact}]}
    original = deepcopy(raw)
    safe = redact_metadata(raw)
    assert contact not in json.dumps(safe) and "private%40" not in json.dumps(safe)
    assert safe["author"][0]["email"] == PLACEHOLDER and raw == original
    assert redact(contact) == PLACEHOLDER


def test_missing_contact_warns_once(monkeypatch, caplog, timer):
    monkeypatch.delenv("CROSSREF_MAILTO", raising=False)
    with fetcher(timer):
        pass
    assert sum("CROSSREF_MAILTO" in r.message for r in caplog.records) == 1


@pytest.mark.parametrize("kwargs", [{"max_pages": 3}, {"max_pages": 0}, {"rows": 0}, {"rows": 1001}])
def test_budget_validation(kwargs, timer):
    with pytest.raises(ValueError):
        fetcher(timer, **kwargs)
