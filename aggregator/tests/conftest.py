"""Keep pytest's empty M0 suite successful without inventing placeholder tests."""

import os

import pytest


def pytest_collection_modifyitems(config, items):
    if os.environ.get("LIVE_TEST") != "1":
        skip = pytest.mark.skip(reason="Network checks require LIVE_TEST=1")
        for item in items:
            if "live" in item.keywords:
                item.add_marker(skip)


def pytest_sessionfinish(session, exitstatus):
    if exitstatus == pytest.ExitCode.NO_TESTS_COLLECTED:
        session.exitstatus = pytest.ExitCode.OK
