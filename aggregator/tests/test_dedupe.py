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


@pytest.mark.parametrize('rss_first',[False,True])
def test_same_source_title_fallback_prefers_doi_without_abstract_transfer(paper,rss_first):
    doi=replace(paper,title='Tax Loss Carryforwards and Firms’ Risk',abstract=None,aliases=[])
    url='https://example.invalid/rss-only'
    rss=replace(doi,id='url:'+url,doi=None,url=url,title='  TAX LOSS Carryforwards and Firms\' Risk. ',
                abstract='Unmatched RSS abstract',aliases=[])
    result=merge_papers([rss,doi] if rss_first else [doi,rss])
    assert len(result)==1 and result[0].id==doi.id and result[0].url==doi.url
    assert result[0].abstract is None and url in result[0].aliases


def test_title_fallback_does_not_merge_sources_or_conflicting_dois(paper):
    from papercart.dedupe import normalize_title
    assert normalize_title('Ａ Model: Growth—Risk')==normalize_title('a model growth-risk')
    original=replace(paper,aliases=[])
    url='https://example.invalid/rss-only'
    rss=replace(original,source='jfe',id='url:'+url,doi=None,url=url,aliases=[])
    assert len(merge_papers([original,rss]))==2
    other=replace(original,doi='10.1111/other',id='doi:10.1111/other',url='https://doi.org/10.1111/other')
    assert len(merge_papers([original,other]))==2
    ambiguous=replace(rss,source=original.source)
    assert len(merge_papers([original,other,ambiguous]))==3


def test_title_fallback_is_exact_not_fuzzy(paper):
    original=replace(paper,title='Growth and Risk',aliases=[])
    url='https://example.invalid/rss-only'
    rss=replace(original,id='url:'+url,doi=None,url=url,title='Growth and Risk: New Evidence',aliases=[])
    assert len(merge_papers([original,rss]))==2
