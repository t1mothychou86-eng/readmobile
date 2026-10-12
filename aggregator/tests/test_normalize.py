from copy import deepcopy

import pytest

from papercart.normalize import normalize_crossref, plain_text, publication_date


@pytest.mark.parametrize("source,fixture,count", [
    ("aer", "crossref-aer-0002-8282.json", 23),
    ("qje", "crossref-qje-0033-5533.json", 18),
    ("jf", "crossref-jf-0022-1082.json", 22),
    ("jpe", "crossref-jpe-0022-3808.json", 24),
    ("jfe", "crossref-jfe-0304-405X.json", 25),
    ("res", "crossref-res-0034-6527.json", 25),
    ("rfs", "crossref-rfs-0893-9454.json", 25),
    ("nber", "crossref-nber.json", 25),
    ("feds", "crossref-feds.json", 10),
])
def test_recorded_source_filtering(sources, fixture_json, source, fixture, count):
    items = fixture_json(fixture)["message"]["items"]
    papers = [p for item in items if (p := normalize_crossref(item, sources[source]))]
    assert len(papers) == count
    assert all(p.id == f"doi:{p.doi}" and p.source == source for p in papers)
    assert all("<jats:" not in (p.abstract or "") for p in papers)


def test_real_journal_fields_and_jats(sources, fixture_json):
    item = fixture_json("crossref-m1-aer-page-1.json")["message"]["items"][0]
    paper = normalize_crossref(item, sources["aer"])
    assert paper is not None
    assert paper.title == plain_text(item["title"][0])
    assert paper.volume == item["volume"]
    assert paper.pages == item["page"]
    assert paper.publication_title == "American Economic Review"
    assert paper.issn == "0002-8282"
    assert paper.kind == "journalArticle" and paper.wp_number is None
    assert paper.abstract and "<" not in paper.abstract
    assert paper.authors[0]["family"] == item["author"][0]["family"]
    assert paper.to_dict()["zotero"] == {}


@pytest.mark.parametrize("source,fixture,expected", [
    ("nber", "crossref-nber.json", "35864"),
    ("feds", "crossref-feds.json", "2026.068"),
])
def test_working_paper_metadata(sources, fixture_json, source, fixture, expected):
    items = fixture_json(fixture)["message"]["items"]
    paper = next(p for item in items if (p := normalize_crossref(item, sources[source])))
    assert paper.kind == "report" and paper.wp_number == expected
    assert paper.institution and paper.series_title == sources[source].name
    assert paper.publication_title is None


def test_ecta_year_precision_and_missing_abstract(sources, fixture_json):
    paper = normalize_crossref(fixture_json("ecta-current-doi.json")["message"], sources["ecta"])
    assert paper.published == "2026"
    item = fixture_json("crossref-jpe-0022-3808.json")["message"]["items"][0]
    assert normalize_crossref(item, sources["jpe"]).abstract is None


def test_recorded_ecta_date_controls(fixture_json):
    year = fixture_json("ecta-date-control-year-start.json")["message"]
    window = fixture_json("ecta-date-control-window-start.json")["message"]
    assert year["total-results"] == 1 and window["total-results"] == 0
    assert year["items"][0]["published"]["date-parts"] == [[2026]]
    sample = fixture_json("ecta-year-sample.json")["message"]
    assert len(sample["items"]) == 25
    assert all(i["type"] == "journal-article" and i["published"]["date-parts"] == [[2026]] for i in sample["items"])


@pytest.mark.parametrize("value,expected", [
    ("<jats:p>First &amp; second.</jats:p><jats:p>H<sub>2</sub>O.</jats:p>", "First & second. H2O."),
    ("&lt;jats:p&gt;A &amp;amp; B&lt;/jats:p&gt;", "A & B"),
    ("<jats:p>Safe<script>ignore()</script><style>ignore</style> text.</jats:p>", "Safe text."),
    (None, ""),
])
def test_plain_text(value, expected):
    assert plain_text(value) == expected


@pytest.mark.parametrize("title", ["Front Matter", "Backmatter", "Correction to: A model", "Erratum: A model", "Editorial Report", "Editor’s Report", "Report of the Editor", "Acknowledgments to Referees", "List of Referees 2026", "ANNOUNCEMENTS"])
def test_non_papers_are_excluded(title, sources, fixture_json):
    item = fixture_json("crossref-aer-0002-8282.json")["message"]["items"][0]
    item["title"] = [title]
    assert normalize_crossref(item, sources["aer"]) is None


@pytest.mark.parametrize("title", ["Error Correction in Asset Prices", "Editorial Influence on Research", "The Report of the Editor as Economic Evidence", "Front Matter Pricing in Publishing Markets"])
def test_research_titles_not_overfiltered(title, sources, fixture_json):
    item = fixture_json("crossref-aer-0002-8282.json")["message"]["items"][0]
    item["title"] = [title]
    assert normalize_crossref(item, sources["aer"]).title == title


@pytest.mark.parametrize("field,value", [("DOI", ""), ("title", []), ("type", "book-chapter")])
def test_unusable_records_rejected(field, value, sources, fixture_json):
    item = fixture_json("crossref-aer-0002-8282.json")["message"]["items"][0]
    item[field] = value
    assert normalize_crossref(item, sources["aer"]) is None


def test_doi_case_normalized_and_original_unchanged(sources, fixture_json):
    item = fixture_json("crossref-nber.json")["message"]["items"][0]
    item["DOI"] = item["DOI"].upper()
    original = deepcopy(item)
    assert normalize_crossref(item, sources["nber"]).doi == "10.3386/w35864"
    assert item == original


@pytest.mark.parametrize("source,doi", [("nber", "10.3386/c10001"), ("nber", "10.3386/w123x"), ("feds", "10.17016/ifdp.2026.1"), ("feds", "10.17016/2380-7172.1")])
def test_other_series_excluded(source, doi, sources, fixture_json):
    item = fixture_json("crossref-nber.json")["message"]["items"][0]
    item["DOI"] = doi
    assert normalize_crossref(item, sources[source]) is None


@pytest.mark.parametrize("parts,expected", [([2026], "2026"), ([2026, 9], "2026-09"), ([2026, 9, 30], "2026-09-30"), ([2026, 2, 30], None), ([True], None)])
def test_date_precision_and_validity(parts, expected):
    assert publication_date({"published": {"date-parts": [parts]}}) == expected


def test_date_fallback():
    assert publication_date({"published": {}, "published-online": {"date-parts": [[2026, 8]]}}) == "2026-08"


def test_named_creator_and_missing_authors(sources, fixture_json):
    item = fixture_json("crossref-aer-0002-8282.json")["message"]["items"][0]
    item["author"] = [{"name": "Research Institute"}, {}, None]
    assert normalize_crossref(item, sources["aer"]).authors == [{"given": "", "family": "Research Institute"}]
    item.pop("author")
    assert normalize_crossref(item, sources["aer"]).authors == []


def test_malformed_working_paper_type_is_skipped(sources, fixture_json):
    item = fixture_json("crossref-nber.json")["message"]["items"][0]
    item["type"] = ["report"]
    assert normalize_crossref(item, sources["nber"]) is None
