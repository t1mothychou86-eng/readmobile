"""Validate our checked-in JSON Schema using its deliberately small keyword set.

No jsonschema dependency: only stdlib, as required by the dependency whitelist.
This is a validator for this schema's subset, not a general JSON Schema engine.
"""

from datetime import date, datetime
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

SCHEMA_PATH = Path(__file__).resolve().parents[2] / "feed.schema.json"
KEYWORDS = {"$schema", "title", "description", "type", "properties", "required", "additionalProperties", "items", "enum", "const", "pattern", "minLength", "minimum", "format"}


def _matches(value, kind):
    return {"null": value is None, "object": isinstance(value, dict), "array": isinstance(value, list),
            "string": isinstance(value, str), "integer": type(value) is int,
            "number": type(value) in (int, float), "boolean": type(value) is bool}[kind]


def validate(value, schema, path="feed"):
    if set(schema) - KEYWORDS:
        raise ValueError("Unsupported schema keywords")
    types = schema.get("type")
    if types and not any(_matches(value, t) for t in (types if isinstance(types, list) else [types])):
        raise ValueError(f"{path}: wrong type")
    if "const" in schema and (type(value) is not type(schema["const"]) or value != schema["const"]):
        raise ValueError(f"{path}: wrong constant")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError(f"{path}: unsupported value")
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                raise ValueError(f"{path}: missing {key}")
        properties = schema.get("properties", {})
        for key, item in value.items():
            if key in properties:
                validate(item, properties[key], f"{path}.{key}")
            elif schema.get("additionalProperties") is False:
                raise ValueError(f"{path}: unexpected field")
            elif isinstance(schema.get("additionalProperties"), dict):
                validate(item, schema["additionalProperties"], f"{path}.{key}")
    if isinstance(value, list) and "items" in schema:
        for index, item in enumerate(value):
            validate(item, schema["items"], f"{path}[{index}]")
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0) or ("pattern" in schema and not re.search(schema["pattern"], value)):
            raise ValueError(f"{path}: invalid string")
        if schema.get("format") == "date-time":
            try:
                if datetime.fromisoformat(value.replace("Z", "+00:00")).tzinfo is None:
                    raise ValueError("Missing timezone")
            except ValueError:
                raise ValueError(f"{path}: invalid timestamp") from None
        if schema.get("format") == "uri":
            try:
                u = urlsplit(value)
                if u.scheme not in {"http", "https"} or not u.hostname or u.username or u.password:
                    raise ValueError("Invalid URI")
            except ValueError:
                raise ValueError(f"{path}: invalid URL") from None
    if type(value) in (int, float) and "minimum" in schema and value < schema["minimum"]:
        raise ValueError(f"{path}: below minimum")


def validate_feed(feed):
    validate(feed, json.loads(SCHEMA_PATH.read_text()))
    sources = {s["id"] for s in feed["sources"]}
    if len(sources) != len(feed["sources"]):
        raise ValueError("Duplicate source IDs")
    seen = set()
    for paper in feed["papers"]:
        if paper["source"] not in sources or paper["id"] in seen:
            raise ValueError("Unknown source or duplicate paper ID")
        seen.add(paper["id"])
        if paper["doi"] and paper["id"] != "doi:" + paper["doi"]:
            raise ValueError("Paper ID does not match DOI")
        if not paper["doi"] and paper["id"] != "url:" + paper["url"]:
            raise ValueError("Paper ID does not match URL")
        if paper["published"]:
            parts = [int(v) for v in paper["published"].split("-")]
            date(parts[0], parts[1] if len(parts) > 1 else 1, parts[2] if len(parts) > 2 else 1)
        if paper["date_precision"] != ("published" if paper["published"] else "first_seen"):
            raise ValueError("Date provenance does not match paper metadata")
