from copy import deepcopy
from datetime import datetime, date, timezone
import json
from pathlib import Path

import httpx
import pytest

from papercart.build import build_feed, in_window, write_feed
from papercart.network import Pacer
from papercart.schema import validate_feed, validate
from papercart.sources import load_sources
from papercart.state import State

FOLDER = Path(__file__).parent / "fixtures/m2/build"
NOW = datetime(2026, 10, 12, 18, tzinfo=timezone.utc)


def replay_client():
    manifest = json.loads((FOLDER/"manifest.json").read_text())
    unused = list(manifest)
    def handler(request):
        params = {k:v for k,v in request.url.params.items() if k not in {"mailto", "api_key"}}
        match = next((r for r in unused if r["url"] == str(request.url.copy_with(query=None)) and r["method"] == request.method and r["params"] == params), None)
        if match is None:
            raise AssertionError("No matching recorded metadata request")
        unused.remove(match)
        file = FOLDER/match["fixture"]
        headers = dict(match["headers"])
        headers["content-type"] = "application/json" if file.suffix == ".json" else "application/rss+xml"
        return httpx.Response(match["status"], content=file.read_bytes(), headers=headers)
    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.fixture
def replay_feed(tmp_path):
    with replay_client() as client:
        return build_feed(load_sources(), client=client, now=NOW, state=State(tmp_path/"state.json"),
                          pacer=Pacer(sleep=lambda _: None, clock=lambda:0), enrich=False)


def test_recorded_complete_build_and_schema(replay_feed):
    validate_feed(replay_feed)
    assert len(replay_feed["papers"]) == 610
    by_source = {s["id"]:s for s in replay_feed["sources"]}
    assert by_source["ecta"]["count"] == 12 and by_source["ecta"]["abstract_count"] == 12
    assert by_source["nber"]["count"] == 222
    assert by_source["nber"]["abstract_count"] == 22
    assert by_source["jfe"]["count"] == 62
    assert by_source["ecb"]["count"] == 14
    assert by_source["bfi"]["status"] == "disabled"
    assert all(p["zotero"] == {} for p in replay_feed["papers"])


@pytest.mark.parametrize("published,expected", [(None,False),("2026",True),("2026-06",True),("2026-06-01",False),("2026-11",False),("2026-02-30",False),("2026-10-12",True)])
def test_window_handles_date_precision(published, expected):
    assert in_window(published, date(2026,6,14), date(2026,10,12)) is expected


def test_retains_recent_previous_records_on_source_failure(replay_feed, tmp_path):
    def failure(request):
        return httpx.Response(503)
    with httpx.Client(transport=httpx.MockTransport(failure)) as client:
        feed = build_feed(load_sources(), client=client, now=NOW, state=State(tmp_path/"state.json"), previous=replay_feed,
                          pacer=Pacer(sleep=lambda _:None, clock=lambda:0), enrich=False)
    assert len(feed["papers"]) == 610
    assert next(s for s in feed["sources"] if s["id"] == "ecta")["status"] == "partial"


@pytest.mark.parametrize("mutation", ["missing", "unknown_field", "bad_source", "duplicate", "bad_date", "bad_type", "bad_precision", "missing_first_seen"])
def test_schema_rejects_invalid_feed(replay_feed, mutation):
    feed = deepcopy(replay_feed)
    if mutation == "missing":feed["papers"][0].pop("title")
    if mutation == "unknown_field":feed["papers"][0]["credentials"] = "not allowed"
    if mutation == "bad_source":feed["papers"][0]["source"] = "unknown"
    if mutation == "duplicate":feed["papers"].append(feed["papers"][0])
    if mutation == "bad_date":feed["papers"][0]["published"] = "2026-02-30"
    if mutation == "bad_type":feed["schema"] = True
    if mutation == "bad_precision":feed["papers"][0]["date_precision"] = "first_seen" if feed["papers"][0]["published"] else "published"
    if mutation == "missing_first_seen":feed["papers"][0].pop("first_seen")
    with pytest.raises(ValueError):validate_feed(feed)


def test_invalid_write_preserves_previous_file(replay_feed, tmp_path):
    out=tmp_path/"feed.json"
    write_feed(replay_feed,out)
    before=out.read_bytes()
    replay_feed["papers"][0].pop("doi")
    with pytest.raises(ValueError):write_feed(replay_feed,out)
    assert out.read_bytes()==before


def test_schema_validator_rejects_unimplemented_keywords():
    with pytest.raises(ValueError, match="Unsupported"):
        validate({}, {"type":"object","anyOf":[]})


def test_pacer_spacing_and_host_circuit():
    clock=[0.0];sleeps=[]
    def sleep(seconds):sleeps.append(seconds);clock[0]+=seconds
    pacer=Pacer(sleep=sleep,clock=lambda:clock[0])
    def respond(request):return httpx.Response(429,headers={"Retry-After":"3600"}) if request.url.host=="limited.invalid" else httpx.Response(200)
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        pacer.request(client,"GET","https://limited.invalid/rss.xml")
        with pytest.raises(httpx.RequestError):pacer.request(client,"GET","https://limited.invalid/rss.xml")
        pacer.request(client,"GET","https://other.invalid/rss.xml")
    assert sleeps==[1.0] and pacer.blocked["limited.invalid"]==3600


def test_state_reuse_without_previous_feed_or_available_sources(replay_feed, tmp_path):
    from papercart.normalize import Paper
    path = tmp_path/"state.json"
    state = State(path)
    state.remember([Paper(**p) for p in replay_feed["papers"]]);state.save()
    with httpx.Client(transport=httpx.MockTransport(lambda request:httpx.Response(503))) as client:
        second = build_feed(load_sources(), client=client, now=NOW, state=State(path),
                            pacer=Pacer(sleep=lambda _:None, clock=lambda:0), enrich=False)
    assert {p['id']:p['first_seen'] for p in second['papers']} == {p['id']:p['first_seen'] for p in replay_feed['papers']}
    nber = [p for p in second['papers'] if p['source']=='nber']
    assert len(nber)==222 and sum(bool(p['abstract']) for p in nber)==22


def test_build_nber_same_doi_uses_rss_abstract(tmp_path, sources, fixture_json):
    sid=sources['nber'];item=fixture_json('crossref-nber.json')['message']['items'][0]
    doi=item['DOI'];number=doi.split('/w')[1]
    def handler(request):
        if request.url.host=='api.crossref.org':
            copy=deepcopy(item);copy['abstract']='Crossref version'
            return httpx.Response(200,json={'status':'ok','message':{'items':[copy],'total-results':1}})
        return httpx.Response(200,text=f'<rss version="2.0"><channel><title>NBER</title><link>https://www.nber.org</link><description>Working papers</description><item><title>Paper</title><link>https://www.nber.org/papers/w{number}</link><description>RSS version</description></item></channel></rss>')
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        feed=build_feed([sid],client=client,now=NOW,state=State(tmp_path/'state.json'),
                        pacer=Pacer(sleep=lambda _:None,clock=lambda:0),enrich=False)
    assert len(feed['papers'])==1 and feed['papers'][0]['abstract']=='RSS version'
    assert feed['papers'][0]['doi']==doi and feed['papers'][0]['date_precision']=='published'
