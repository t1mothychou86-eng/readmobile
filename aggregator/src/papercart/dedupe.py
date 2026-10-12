"""DOI/URL merge, with an exact same-source title fallback for missing DOI.

Title fallback joins identities, never fills abstracts without a matching DOI.
"""

from dataclasses import replace
import re
import unicodedata
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .normalize import Paper, plain_text


def normalize_title(value: str) -> str:
    text = unicodedata.normalize("NFKC", plain_text(value)).casefold()
    return re.sub(r"[\W_]+", " ", text).strip()


def normalize_url(value: str) -> str:
    try:
        u = urlsplit(value)
        if u.scheme not in {"http", "https"} or not u.hostname or u.username or u.password:
            return ""
        port = u.port
        host = u.hostname.lower()
        if ":" in host:
            host = f"[{host}]"
        netloc = host + (f":{port}" if port and port not in (80, 443) else "")
        path = re.sub(r"/{2,}", "/", u.path).rstrip("/") or "/"
        query = sorted((k, v) for k, v in parse_qsl(u.query, keep_blank_values=True)
                       if not k.lower().startswith("utm_") and k.lower() not in {"rss", "af", "dgcid", "fbclid", "gclid"})
        return urlunsplit(("https", netloc, path, urlencode(query), ""))
    except ValueError:
        return ""


def _urls(paper):
    return {u for raw in [paper.url, *paper.aliases] if (u := normalize_url(raw))}


def merge_papers(papers: list[Paper]) -> list[Paper]:
    groups: list[Paper] = []
    by_doi, by_url, by_title = {}, {}, {}
    # DOI records are canonical even when a sparse RSS record arrived first.
    # Stable ordering preserves the caller's primary choice among DOI records.
    for incoming in sorted(papers, key=lambda p: not bool(p.doi)):
        urls = _urls(incoming)
        index = by_doi.get(incoming.doi) if incoming.doi else None
        if index is None:
            index = next((by_url[u] for u in sorted(urls) if u in by_url and
                          (not incoming.doi or not groups[by_url[u]].doi or incoming.doi == groups[by_url[u]].doi)), None)
        if index is None and not incoming.doi:
            candidates = by_title.get((incoming.source, normalize_title(incoming.title)), [])
            # Conflicting DOIs with the same title are ambiguous; don't guess.
            if len(candidates) == 1:
                index = candidates[0]
        if index is None:
            index = len(groups)
            groups.append(incoming)
        else:
            old = groups[index]
            # Caller orders primary metadata first. Crossref authors/fields may
            # fill sparse RSS records; abstracts require the exact SAME DOI.
            same_doi = bool(old.doi and old.doi == incoming.doi)
            doi = old.doi or incoming.doi
            updates = {}
            for field in ("authors", "wp_number", "publication_title", "journal_abbreviation", "volume", "issue", "pages", "issn", "institution", "series_title"):
                updates[field] = getattr(old, field) or getattr(incoming, field)
            updates["published"] = old.published or incoming.published
            if old.published and incoming.published and len(incoming.published) > len(old.published) and incoming.published.startswith(old.published):
                updates["published"] = incoming.published
            updates["abstract"] = old.abstract or (incoming.abstract if same_doi else None)
            updates["first_seen"] = min((v for v in (old.first_seen, incoming.first_seen) if v), default=None)
            updates["date_precision"] = "published" if updates["published"] else "first_seen"
            groups[index] = replace(old, **updates, doi=doi, id=f"doi:{doi}" if doi else old.id,
                                    url=f"https://doi.org/{doi}" if doi and not old.doi else old.url,
                                    aliases=sorted(_urls(old) | urls))
        merged = groups[index]
        if merged.doi:
            by_doi[merged.doi] = index
            title_key = (merged.source, normalize_title(merged.title))
            if title_key[1] and index not in by_title.setdefault(title_key, []):
                by_title[title_key].append(index)
        for u in urls | _urls(merged):
            by_url[u] = index
    # A late DOI record can bridge a URL-only record and an existing DOI record.
    # Repeat once after identities/aliases were promoted; never merge conflicting DOIs.
    if len(groups) < len(papers):
        remaining = []
        seen_doi, seen_urls = {}, {}
        collision = False
        for paper in groups:
            keys = _urls(paper)
            old = seen_doi.get(paper.doi) if paper.doi else None
            if old is None:
                old = next((seen_urls[u] for u in keys if u in seen_urls and
                            (not paper.doi or not remaining[seen_urls[u]].doi or paper.doi == remaining[seen_urls[u]].doi)), None)
            if old is not None:
                collision = True
                break
            idx = len(remaining)
            remaining.append(paper)
            if paper.doi:
                seen_doi[paper.doi] = idx
            for u in keys:
                seen_urls[u] = idx
        if collision:
            return merge_papers(groups)
    return groups
