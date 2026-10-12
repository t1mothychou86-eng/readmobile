"""Pure metadata mapping; field allowlists are pinned to the M0 templates.

No network or library-specific collections/tags. Never turn first_seen into date.
"""

from .normalize import Paper

# Source identities verified in the recorded Crossref/RSS metadata (M0/M2).
REPORT_SERIES = {
    "nber": ("National Bureau of Economic Research", "NBER Working Papers"),
    "feds": ("Board of Governors of the Federal Reserve System", "Finance and Economics Discussion Series"),
    "ecb": ("European Central Bank", "Working Paper Series"),
    "bis": ("Bank for International Settlements", "BIS Working Papers"),
}

# Full top-level field sets from fixtures/zotero-{journalArticle,report}.json.
# A fixture equality test detects drift without loading test files at runtime.
TEMPLATE_FIELDS = {
    "journalArticle": frozenset("itemType title creators abstractNote publicationTitle publisher place date volume issue section partNumber partTitle pages series seriesTitle seriesText journalAbbreviation DOI citationKey url accessDate PMID PMCID ISSN archive archiveLocation shortTitle language libraryCatalog callNumber rights extra tags collections relations".split()),
    "report": frozenset("itemType title creators abstractNote reportNumber reportType institution place date seriesTitle seriesNumber pages DOI ISBN citationKey url accessDate ISSN archive archiveLocation shortTitle language libraryCatalog callNumber rights extra tags collections relations".split()),
}


def validate_zotero(item: dict) -> None:
    """Reject fields outside the recorded item-type template and creator shapes."""
    kind = item.get("itemType")
    if kind not in TEMPLATE_FIELDS or set(item) - TEMPLATE_FIELDS[kind]:
        raise ValueError("Zotero fields outside the M0 template")
    if "collections" in item or "tags" in item:
        raise ValueError("Collections and tags belong to the frontend")
    if not item.get("title") or not isinstance(item.get("creators"), list):
        raise ValueError("Missing Zotero title/creators")
    for creator in item["creators"]:
        keys = set(creator)
        if creator.get("creatorType") != "author" or keys not in (
            {"creatorType", "firstName", "lastName"}, {"creatorType", "name"}
        ) or any(not isinstance(v, str) for v in creator.values()):
            raise ValueError("Invalid Zotero creator")
        if not (creator.get("name") or creator.get("firstName") or creator.get("lastName")):
            raise ValueError("Empty Zotero creator")
    if kind == "report" and (item.get("reportType") != "Working Paper" or not item.get("institution") or not item.get("seriesTitle")):
        raise ValueError("Missing working-paper series metadata")


def to_zotero(paper: Paper) -> dict:
    """Return editable Zotero JSON using only metadata actually present."""
    if paper.kind not in TEMPLATE_FIELDS:
        raise ValueError("Unsupported Zotero item type")
    creators = []
    for author in paper.authors:
        given = author.get("given", "")
        family = author.get("family", "") or author.get("name", "")
        if given:
            creators.append({"creatorType": "author", "firstName": given, "lastName": family})
        elif family:
            creators.append({"creatorType": "author", "name": family})
    item = {"itemType": paper.kind, "title": paper.title, "creators": creators}
    fields = {"abstractNote": paper.abstract, "DOI": paper.doi, "url": paper.url, "date": paper.published}
    if paper.kind == "journalArticle":
        fields.update(publicationTitle=paper.publication_title, journalAbbreviation=paper.journal_abbreviation,
                      volume=paper.volume, issue=paper.issue, pages=paper.pages, ISSN=paper.issn)
    else:
        if paper.source not in REPORT_SERIES:
            raise ValueError("Unsupported working-paper source")
        institution, series = REPORT_SERIES[paper.source]
        fields.update(reportType="Working Paper", institution=institution, seriesTitle=series, reportNumber=paper.wp_number)
    item.update({key: value for key, value in fields.items() if value is not None and value != ""})
    assert set(item) <= TEMPLATE_FIELDS[paper.kind], "Zotero fields outside the M0 template"
    validate_zotero(item)
    return item
