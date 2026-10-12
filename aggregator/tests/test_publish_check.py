from pathlib import Path
import json
import subprocess

import pytest

from papercart.publish_check import check_publication, check_state, main
from papercart.state import State
from test_build import NOW, replay_feed  # Reuse the recorded, offline build fixture.


@pytest.fixture
def publication(replay_feed, tmp_path):
    from papercart.normalize import Paper
    feed_path = tmp_path / 'feed.json'
    feed_path.write_text(json.dumps(replay_feed))
    state = State(tmp_path / 'state.json')
    state.remember([Paper(**p) for p in replay_feed['papers']])
    state.data['semantic_scholar']['entries']['10.3386/w12345'] = {'abstract': 'Public abstract', 'expires': 1}
    state.save()
    return feed_path, state.path


def test_recorded_publication_is_safe(publication):
    assert check_publication(*publication) == 586


@pytest.mark.parametrize('has_history', [False, True])
def test_unavailable_sources_publish_only_with_nonempty_history(publication, has_history):
    import httpx
    from papercart.build import build_feed, write_feed
    from papercart.network import Pacer
    from papercart.sources import load_sources
    feed_path, state_path = publication
    if not has_history:
        state_path.unlink()
    state = State(state_path)
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(503))) as client:
        feed = build_feed(load_sources(), client=client, now=NOW, state=state,
                          pacer=Pacer(sleep=lambda _: None, clock=lambda: 0), enrich=False)
    state.save()
    write_feed(feed, feed_path)
    assert any(source['errors'] for source in feed['sources'])
    if has_history:
        assert check_publication(feed_path, state_path) == 586
    else:
        with pytest.raises(ValueError, match='Empty feed'):
            check_publication(feed_path, state_path)


@pytest.mark.parametrize('mutation', ['email', 'encoded_email', 'headers', 'api_key', 'nested_header', 'request_string', 'cache_extra'])
def test_private_state_blocks_publication(publication, mutation):
    feed, path = publication
    data = json.loads(path.read_text())
    record = next(iter(data['papers'].values()))
    # Synthetic contacts only; never read a real secret into test output.
    if mutation == 'email':
        record['paper']['abstract'] = 'Contact synthetic@example.invalid'
    elif mutation == 'encoded_email':
        record['aliases'].append('https://example.invalid/?contact=synthetic%2540example.invalid')
    elif mutation == 'headers':
        data['headers'] = {'Authorization': 'Bearer synthetic'}
    elif mutation == 'api_key':
        data['api_key'] = 'synthetic'
    elif mutation == 'nested_header':
        record['paper']['headers'] = {'Accept': 'application/json'}
    elif mutation == 'request_string':
        record['paper']['abstract'] = 'Zotero-API-Key: synthetic'
    else:
        data['semantic_scholar']['entries']['10.3386/w12345']['request'] = {}
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        check_publication(feed, path)


def test_saved_state_redacts_contacts(publication):
    feed, path = publication
    state = State(path)
    next(iter(state.data['papers'].values()))['paper']['abstract'] = 'synthetic@example.invalid'
    state.save()
    assert 'synthetic@' not in path.read_text()
    assert check_publication(feed, path) == 586


def test_expired_unmapped_observation_is_safe(publication):
    data = json.loads(publication[1].read_text())
    next(iter(data['papers'].values()))['paper']['zotero'] = {}
    check_state(data)


@pytest.mark.parametrize('mutation', ['empty', 'schema'])
def test_bad_feed_blocks_publication(publication, mutation):
    feed, state = publication
    data = json.loads(feed.read_text())
    if mutation == 'empty':
        data['papers'] = []
    else:
        data['schema'] = 999
    feed.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        check_publication(feed, state)


def test_validation_cli_fails_without_printing_sensitive_details(publication, monkeypatch, capsys):
    feed, state = publication
    state.write_text('{"private": "synthetic@example.invalid"}')
    monkeypatch.setattr('sys.argv', ['publish_check', '--feed', str(feed), '--state', str(state)])
    assert main() == 1
    assert 'synthetic' not in capsys.readouterr().out


@pytest.mark.parametrize('success', [False, True])
def test_restore_state_curl_success_and_failure(tmp_path, monkeypatch, success):
    # Mock curl as an executable: exercise the actual shell script offline.
    bin_path = tmp_path / 'bin'
    bin_path.mkdir()
    curl = bin_path / 'curl'
    curl.write_text('#!/usr/bin/env python3\nimport sys\nfrom pathlib import Path\n'
                    'target = Path(sys.argv[sys.argv.index("--output") + 1])\n'
                    'target.write_text("restored" if ' + repr(success) + ' else "partial")\n'
                    'sys.exit(' + ('0' if success else '22') + ')\n')
    curl.chmod(0o755)
    import os
    monkeypatch.setenv('PATH', str(bin_path) + os.pathsep + os.environ['PATH'])
    monkeypatch.setenv('SITE_URL', 'https://example.invalid/project/')
    state = tmp_path / 'public/data/state.json'
    state.parent.mkdir(parents=True)
    state.write_text('stale state')
    script = Path(__file__).resolve().parents[2] / 'scripts/restore-state.sh'
    result = subprocess.run(['bash', str(script), str(state)], capture_output=True, text=True)
    assert result.returncode == 0
    assert not state.with_suffix('.json.tmp').exists()
    if success:
        assert state.read_text() == 'restored'
    else:
        assert not state.exists()
        assert State(state).history() == []
        assert 'empty state' in result.stdout
