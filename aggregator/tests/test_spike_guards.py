import importlib.util
from pathlib import Path

import httpx
import pytest
import respx


@pytest.fixture
def spike(monkeypatch, tmp_path):
    script = Path(__file__).resolve().parents[1] / "scripts/spike.py"
    spec = importlib.util.spec_from_file_location("m0_spike", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "FIXTURES", tmp_path)
    monkeypatch.setattr(module, "wait_headers", lambda headers: None)
    monkeypatch.setattr(module.time, "sleep", lambda seconds: None)
    return module


@respx.mock
@pytest.mark.parametrize("url", ["https://example.invalid/paper.pdf", "https://api.zotero.org/doi/full/1", "https://onlinelibrary.wiley.com/doi/pdf/10.1111/test", "https://onlinelibrary.wiley.com/doi/full/10.1111/test"])
def test_probe_rejects_pdf_and_fulltext_before_request(spike, url):
    with httpx.Client() as client:
        result, body = spike.probe(client, "unused.json", url)
    assert result["error"] == "ValueError" and body == "" and len(respx.calls) == 0


@respx.mock
def test_probe_rejects_fulltext_redirect(spike):
    url = "https://api.zotero.org/items/new"
    respx.get(url).respond(302, headers={"Location": "https://api.zotero.org/doi/full/1"})
    with httpx.Client(follow_redirects=True) as client:
        result, body = spike.probe(client, "unused.json", url)
    assert result["error"] == "ValueError" and len(respx.calls) == 1 and body == ""
