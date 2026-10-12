"""Fail closed before uploading public feed/state to Pages (no network)."""

import argparse
import json
import math
from pathlib import Path
import re
from urllib.parse import unquote

from .privacy import EMAIL, PLACEHOLDER
from .schema import SCHEMA_PATH, validate, validate_feed
from .state import State, timestamp

REQUEST_SECRET = re.compile(
    r"authorization|proxy-authorization|zotero-api-key|zotero-write-token|"
    r"\b(?:api[_-]?key|access[_-]?token|mailto)\s*[:=]|\b(?:bearer|basic)\s+\S+",
    re.I,
)


def check_private(value):
    if isinstance(value, dict):
        for key, item in value.items():
            check_private(key)
            check_private(item)
    elif isinstance(value, list):
        for item in value:
            check_private(item)
    elif isinstance(value, str):
        decoded = unquote(unquote(value)).replace(PLACEHOLDER, '')
        if EMAIL.search(decoded) or REQUEST_SECRET.search(decoded):
            raise ValueError('Public metadata contains contact or request secrets')


def exact_fields(value, fields):
    if not isinstance(value, dict) or set(value) != set(fields):
        raise ValueError('Unexpected public state fields')


def check_state(data):
    """Allow only persisted paper metadata and S2 abstracts/cooldown."""
    check_private(data)
    exact_fields(data, {'schema', 'papers', 'semantic_scholar'})
    if type(data['schema']) is not int or data['schema'] != 1 or not isinstance(data['papers'], dict):
        raise ValueError('Invalid public state schema')
    paper_schema = json.loads(SCHEMA_PATH.read_text())['properties']['papers']['items']
    for identity, record in data['papers'].items():
        exact_fields(record, {'first_seen', 'paper', 'aliases'})
        timestamp(record['first_seen'])
        # Out-of-window observations are persisted before Zotero mapping;
        # their empty mapping is valid state, though never valid public feed.
        schema = paper_schema
        if record['paper'].get('zotero') == {}:
            schema = {**paper_schema, 'properties': {**paper_schema['properties'],
                      'zotero': {'type': 'object', 'additionalProperties': False}}}
        validate(record['paper'], schema)
        if identity != record['paper']['id'] or record['first_seen'] != record['paper']['first_seen']:
            raise ValueError('Inconsistent public state identity/date')
        validate(record['aliases'], {'type': 'array', 'items': {'type': 'string', 'format': 'uri'}})
    cache = data['semantic_scholar']
    exact_fields(cache, {'entries', 'blocked_until'})
    if not isinstance(cache['entries'], dict):
        raise ValueError('Invalid public abstract cache')
    numbers = [cache['blocked_until']]
    for entry in cache['entries'].values():
        exact_fields(entry, {'abstract', 'expires'})
        if entry['abstract'] is not None and not isinstance(entry['abstract'], str):
            raise ValueError('Invalid public cached abstract')
        numbers.append(entry['expires'])
    if any(type(n) not in (int, float) or not math.isfinite(n) or n < 0 for n in numbers):
        raise ValueError('Invalid public cache timestamps')


def check_publication(feed_path, state_path):
    feed = json.loads(Path(feed_path).read_text(encoding='utf-8'))
    validate_feed(feed)
    if not feed['papers']:
        raise ValueError('Empty feed must not replace the live site')
    check_private(feed)
    # Inspect raw state before State applies its contact redaction.
    check_state(json.loads(Path(state_path).read_text(encoding='utf-8')))
    State(state_path)
    return len(feed['papers'])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--feed', required=True, type=Path)
    parser.add_argument('--state', required=True, type=Path)
    args = parser.parse_args()
    try:
        count = check_publication(args.feed, args.state)
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        print('Publication validation failed; details omitted to protect private metadata')
        return 1
    print(f'Publication validated: {count} papers; state contains only public metadata')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
