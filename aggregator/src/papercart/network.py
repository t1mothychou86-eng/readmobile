"""Pace metadata requests and stop a throttled host for the rest of a run."""

from email.utils import parsedate_to_datetime
from datetime import datetime, timezone
import time

import httpx


def retry_seconds(headers) -> float:
    value = headers.get("Retry-After") or headers.get("Backoff")
    if not value:
        return 60.0
    try:
        return max(1.0, float(value))
    except ValueError:
        try:
            return max(1.0, (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds())
        except (ValueError, TypeError, OverflowError):
            return 60.0


class Pacer:
    def __init__(self, *, sleep=time.sleep, clock=time.monotonic):
        self.sleep, self.clock = sleep, clock
        self.next_request = 0.0
        self.blocked: dict[str, float] = {}

    def request(self, client, method, url, **kwargs):
        host = httpx.URL(url).host
        if host in self.blocked:
            raise httpx.RequestError("Metadata host cooling down")
        delay = self.next_request - self.clock()
        if delay > 0:
            self.sleep(delay)
        try:
            response = client.request(method, url, follow_redirects=False, **kwargs)
        finally:
            self.next_request = self.clock() + 1.0
        if response.status_code in (429, 503):
            self.blocked[host] = retry_seconds(response.headers)
        return response
