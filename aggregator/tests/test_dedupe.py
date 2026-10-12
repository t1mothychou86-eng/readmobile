from dataclasses import replace

import pytest

from papercart.dedupe import normalize_url, merge_papers
from papercart.normalize import normalize_crossref


@pytest.fixture
def paper(sources, fixture_json):
    return normalize_crossref(fixture_json("crossref-aer-0002-8282.json")["message"]["items"][0], sources["aer"])


def test_url_tracking_and_semantic_query_parameters():
    assert normalize_url("http://EXAMPLE.invalid:80//paper/?utm_source=rss&rss=1&version=2#top") == "https://example.invalid/paper?version=2"
    assert normalize_url("https://example.invalid/paper?version=3") != normalize_url("https://example.invalid/paper?version=2")
    assert normalize_url("javascript:alert(1)") == ""
    assert normalize_url("https://user:pass" + "@" + "example.invalid/paper") == ""


def test_same_doi_fills_abstract_and_authors(paper):
    primary = replace(paper, abstract=None, authors=[])
    result = merge_papers([primary, replace(paper, url="https://example.invalid/other")])
    assert len(result) == 1 and result[0].abstract == paper.abstract and result[0].authors == paper.authors


def test_url_only_duplicate_does_not_fill_doi_abstract(paper):
    primary = replace(paper, abstract=None, aliases=["https://example.invalid/paper"])
    rss = replace(paper, id="url:https://example.invalid/paper", doi=None, url="https://example.invalid/paper?utm_source=rss", abstract="RSS abstract")
    result = merge_papers([primary, rss])
    assert len(result) == 1 and result[0].abstract is None


def test_different_dois_never_merge_even_if_url_shared(paper):
    other = replace(paper, doi="10.1111/other", id="doi:10.1111/other", url=paper.url)
    assert len(merge_papers([paper, other])) == 2


def test_transitive_doi_url_bridge(paper):
    url = "https://example.invalid/paper"
    url_only = replace(paper, doi=None, id="url:"+url, url=url, aliases=[])
    separate = replace(paper, aliases=[])
    bridge = replace(paper, aliases=[url])
    result = merge_papers([url_only, separate, bridge])
    assert len(result) == 1 and result[0].doi == paper.doi


def test_partial_date_precision_upgraded(paper):
    result = merge_papers([replace(paper, published="2026"), replace(paper, published="2026-09-22")])
    assert result[0].published == "2026-09-22"
