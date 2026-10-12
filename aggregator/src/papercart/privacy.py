"""Redact contact information before recording metadata or logging requests."""

import logging
import os
import re
from urllib.parse import quote, quote_plus

PLACEHOLDER = "papercart@example.invalid"
EMAIL = re.compile(r"[\w.%+\-]+@[\w.\-]+\.[a-zA-Z]{2,}")
ENCODED_EMAIL = re.compile(r"[\w.%+\-]+%40[\w.\-]+\.[a-zA-Z]{2,}", re.I)


def redact(text: str) -> str:
    contact = os.environ.get("CROSSREF_MAILTO", "")
    if contact:
        for value in (contact, quote(contact, safe=""), quote_plus(contact)):
            text = text.replace(value, PLACEHOLDER)
    return ENCODED_EMAIL.sub(PLACEHOLDER, EMAIL.sub(PLACEHOLDER, text))


def redact_metadata(value):
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, list):
        return [redact_metadata(item) for item in value]
    if isinstance(value, dict):
        return {redact(str(key)): redact_metadata(item) for key, item in value.items()}
    return value


class ContactFilter(logging.Filter):
    def filter(self, record):
        record.msg = redact(record.getMessage())
        record.args = ()
        return True


def protect_http_logs() -> None:
    # httpx emits request URLs (including mailto) at INFO. Install on the
    # emitting logger; a filter on a parent would not filter propagated records.
    logger = logging.getLogger("httpx")
    if not any(isinstance(f, ContactFilter) for f in logger.filters):
        logger.addFilter(ContactFilter())
