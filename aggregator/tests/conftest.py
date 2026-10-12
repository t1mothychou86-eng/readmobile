"""Offline fixture tests; live checks require explicit opt-in."""

import os
from pathlib import Path
import json
import socket

import pytest

from papercart.privacy import PLACEHOLDER
from papercart.sources import load_sources


@pytest.fixture(autouse=True)
def offline_and_private(monkeypatch, request):
    # Keep the developer's real environment contact out of mock request URLs,
    # pytest failure introspection and captured logs. Live checks explicitly opt in.
    if "live" not in request.node.keywords:
        monkeypatch.setenv("CROSSREF_MAILTO", PLACEHOLDER)
        def blocked(*args, **kwargs):
            raise AssertionError("Unit tests must not access the network")
        monkeypatch.setattr(socket.socket, "connect", blocked)
        monkeypatch.setattr(socket.socket, "connect_ex", blocked)


@pytest.fixture
def fixture_json():
    folder = Path(__file__).parent / "fixtures"
    return lambda name: json.loads((folder / name).read_text(encoding="utf-8"))


@pytest.fixture
def sources():
    return {source.id: source for source in load_sources()}


def pytest_collection_modifyitems(config, items):
    if os.environ.get("LIVE_TEST") != "1":
        skip = pytest.mark.skip(reason="Network checks require LIVE_TEST=1")
        for item in items:
            if "live" in item.keywords:
                item.add_marker(skip)
