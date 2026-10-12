from dataclasses import replace
from pathlib import Path

import feedparser
import httpx
import pytest
import respx

from papercart.rss import RSSFetcher, normalize_entry
from papercart.sources import RSSConfig
from papercart.network import Pacer

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def pacer():
    return Pacer(sleep=lambda _: None, clock=lambda: 0)


@pytest.mark.parametrize("sid,total,abstracts", [("qje",15,15),("jpe",18,0),("ecta",12,12),("res",18,18),("jf",34,33),("jfe",32,0),("rfs",8,8),("nber",22,22),("feds",15,15),("ecb",14,14),("bis",25,25)])
def test_recorded_rss_metadata(sid, total, abstracts, sources):
    name = "rss-rfs-correct.xml" if sid == "rfs" else f"rss-{sid}.xml"
    data = feedparser.parse((FIXTURES / name).read_bytes())
    papers = [p for e in data.entries if (p := normalize_entry(e, sources[sid]))]
    assert len(papers) == total and sum(bool(p.abstract) for p in papers) == abstracts
    assert all("<jats:" not in (p.abstract or "") for p in papers)
    if sid == "ecta":
        assert all(p.doi and p.published.startswith("2026-09") and p.authors for p in papers)
    if sid == "nber":
        assert all(p.doi.startswith("10.3386/w") and " -- by " not in p.title for p in papers)


def test_d4_configuration_selects_field(sources):
    data = feedparser.parse((FIXTURES / "rss-ecta.xml").read_bytes())
    entry = data.entries[2]
    paper = normalize_entry(entry, sources["ecta"])
    assert paper.abstract.startswith("We propose a framework")
    entry["summary"] = "<p>Description abstract</p>"
    source = replace(sources["ecta"], rss=RSSConfig(sources["ecta"].rss.url, "description"))
    assert normalize_entry(entry, source).abstract == "Description abstract"


@respx.mock
def test_ecb_pdf_is_saved_but_never_requested(sources, pacer):
    url = sources["ecb"].rss.url
    respx.get(url).respond(200, content=(FIXTURES / "rss-ecb.xml").read_bytes())
    with httpx.Client() as client:
        result = RSSFetcher(client, pacer=pacer).fetch(sources["ecb"])
    assert result.status == "ok" and len(respx.calls) == 1
    assert all(p.url.endswith(".pdf") and p.id == "url:" + p.url for p in result.papers)
    # E1: dp32 was filtered; all emitted ECB records are working papers.
    assert len(result.papers) == 14 and all(p.wp_number for p in result.papers)


@respx.mock
def test_rss_redirect_to_fulltext_not_followed(sources, pacer):
    respx.get(sources["jf"].rss.url).respond(302, headers={"Location": "https://example.invalid/full/paper.pdf"})
    with httpx.Client(follow_redirects=True) as client:
        result = RSSFetcher(client, pacer=pacer).fetch(sources["jf"])
    assert result.status == "unavailable" and result.error == "RSS HTTP 302" and len(respx.calls) == 1


@respx.mock
def test_invalid_rss_and_disabled_source(sources, pacer):
    respx.get(sources["ecb"].rss.url).respond(200, text="<html>not a feed</html>")
    with httpx.Client() as client:
        api = RSSFetcher(client, pacer=pacer)
        assert api.fetch(sources["bfi"]).status == "disabled"
        assert api.fetch(sources["aer"]).status == "not_applicable"
        assert api.fetch(sources["ecb"]).error == "Invalid RSS/Atom metadata response"
    assert len(respx.calls) == 1


@pytest.mark.parametrize("url", ["https://www.ecb.europa.eu/paper.pdf", "https://onlinelibrary.wiley.com/doi/full/1", "https://example.invalid/article/123"])
def test_article_urls_cannot_be_rss_endpoints(url):
    with pytest.raises(ValueError):
        RSSConfig(url, "description")
