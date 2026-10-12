from dataclasses import replace

import pytest
import yaml

from papercart.sources import CrossrefConfig, load_sources
from papercart.normalize import matches_series


def test_decisions_and_configuration(sources):
    assert len(sources) == 13
    assert sources["ecta"].primary == "rss" and sources["ecta"].crossref is not None
    assert sources["bfi"].status == "disabled" and not sources["bfi"].active
    assert matches_series(sources["nber"], "10.3386/w123")
    assert matches_series(sources["feds"], "10.17016/feds.2026.123")


def test_series_policy_survives_overbroad_config(sources):
    source = replace(sources["nber"], crossref=CrossrefConfig(prefix="10.3386", doi_pattern=".*"))
    assert not matches_series(source, "10.3386/c123")


@pytest.mark.parametrize("kwargs", [dict(issn="../../paper.pdf"), dict(prefix="https://example.invalid/full", doi_pattern=".*"), dict(issn="0002-8282", prefix="10.3386"), dict(prefix="10.3386")])
def test_endpoint_identifiers_validated(kwargs):
    with pytest.raises(ValueError):
        CrossrefConfig(**kwargs)


def test_duplicate_and_unverified_sources_rejected(tmp_path, sources):
    entry = {"id": "test", "name": "Test", "short": "T", "group": "finance", "kind": "journal", "verified": "2026-10-13", "status": "passed"}
    path = tmp_path / "sources.yaml"
    path.write_text(yaml.safe_dump({"schema": 1, "sources": [entry, entry]}))
    with pytest.raises(ValueError, match="duplicate"):
        load_sources(path)
    entry["verified"] = None
    path.write_text(yaml.safe_dump({"schema": 1, "sources": [entry]}))
    with pytest.raises(ValueError, match="verified"):
        load_sources(path)


def test_jfe_rss_disable_retains_verified_url():
    from papercart.sources import DEFAULT_CONFIG
    raw=yaml.safe_load(DEFAULT_CONFIG.read_text())
    jfe=next(s for s in raw['sources'] if s['id']=='jfe')
    assert jfe['rss']['enabled'] is False and jfe['rss']['url']
    assert jfe['rss']['verified'] and jfe['rss']['reason']
