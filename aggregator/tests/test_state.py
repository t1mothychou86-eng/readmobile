from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json

import pytest

from papercart.build import effective_date, in_window
from papercart.dedupe import merge_papers
from papercart.normalize import normalize_crossref
from papercart.state import State

NOW = datetime(2026,10,13,tzinfo=timezone.utc)


@pytest.fixture
def paper(sources, fixture_json):
    original = normalize_crossref(fixture_json("crossref-nber.json")["message"]["items"][0], sources["nber"])
    return replace(original, published=None, abstract="RSS abstract")


def test_first_seen_and_abstract_survive_missing_source_and_new_output(paper, tmp_path):
    path = tmp_path/"state.json"
    first = State(path)
    observed = first.observe(paper, NOW)
    assert observed.published is None and observed.date_precision == "first_seen"
    first.remember([observed]);first.save()
    second = State(path)
    fresh = second.observe(replace(paper, abstract=None), NOW+timedelta(days=10))
    assert fresh.first_seen == observed.first_seen and fresh.abstract == "RSS abstract"
    assert second.history()[0].abstract == "RSS abstract"
    assert effective_date(fresh) == "2026-10-13"


def test_undated_expiry_does_not_reset_first_seen(paper, tmp_path):
    state = State(tmp_path/"state.json")
    first = state.observe(paper, NOW);state.remember([first]);state.save()
    later = NOW+timedelta(days=121)
    again = State(state.path).observe(paper, later)
    assert again.first_seen == first.first_seen
    assert not in_window(effective_date(again), later.date()-timedelta(days=120), later.date())


def test_known_publication_date_supersedes_observation_date(paper, tmp_path):
    state = State(tmp_path/"state.json")
    first = state.observe(paper, NOW);state.remember([first]);state.save()
    dated = State(state.path).observe(replace(paper, published="2026-10"), NOW+timedelta(days=1))
    assert dated.first_seen == first.first_seen and dated.date_precision == "published"
    assert effective_date(dated) == "2026-10"


def test_nber_rss_abstract_wins_over_crossref(paper):
    crossref = replace(paper, abstract="Crossref abstract", published="2026-10")
    result = merge_papers([paper, crossref])[0]
    assert result.abstract == "RSS abstract" and result.published == "2026-10"


def test_url_to_doi_promotion_preserves_first_seen(paper, tmp_path):
    url = "https://example.invalid/paper"
    undoi = replace(paper, doi=None, id="url:"+url, url=url, aliases=[])
    first = State(tmp_path/"state.json")
    observed = first.observe(undoi, NOW);first.remember([observed]);first.save()
    promoted = State(first.path).observe(replace(paper, aliases=[url]), NOW+timedelta(days=1))
    assert promoted.first_seen == observed.first_seen


def test_corrupt_state_is_not_silently_reset(tmp_path):
    path = tmp_path/"state.json";path.write_text('{"schema":999}')
    with pytest.raises(ValueError):State(path)


def test_legacy_cache_import_only_once(tmp_path):
    legacy = tmp_path/"legacy.json"
    legacy.write_text(json.dumps({"schema":1,"entries":{},"blocked_until":200}))
    state = State(tmp_path/"state.json")
    assert state.migrate_legacy_cache(legacy)
    assert state.data["semantic_scholar"]["blocked_until"] == 200
    state.save()
    assert not State(state.path).migrate_legacy_cache(legacy)
