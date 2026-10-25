import ipaddress
import re
from urllib.parse import urlsplit, urlunsplit

from .domain import Brief, Evidence, Extraction, Research

EXCLUDED = re.compile(
    r"\b(home address|date of birth|social security|religion|religious|sexual orientation|"
    r"ethnicity|immigration|criminal record|medical condition|political affiliation|"
    r"net worth|spouse|children|minor|underage)\b",
    re.IGNORECASE,
)
INVASIVE = re.compile(r"\b(stalk|surveill|i saw you at home|i know where you live)\w*", re.IGNORECASE)


def safe_url(value: str) -> str | None:
    try:
        p = urlsplit(value)
        host = (p.hostname or "").lower().rstrip(".")
        if p.scheme != "https" or p.username or p.password or p.port not in {443, None}:
            return None
        if not host or "." not in host or host.endswith((".local", ".localhost", ".internal")):
            return None
        if any(
            host == d or host.endswith("." + d)
            for d in ("linkedin.com", "facebook.com", "whitepages.com", "spokeo.com")
        ):
            return None
        try:
            if not ipaddress.ip_address(host).is_global:
                return None
        except ValueError:
            pass
        return urlunsplit(("https", host, p.path or "/", p.query, ""))
    except ValueError:
        return None


def domain(url: str) -> str:
    # Conservative publisher comparison; shared last two labels count only once.
    parts = (urlsplit(url).hostname or "").split(".")
    return ".".join(parts[-2:])


def normalize_org(value: str) -> str:
    words = re.sub(r"[^\w\s]", " ", value.casefold()).split()
    while words and words[-1] in {
        "corporation", "corp", "incorporated", "inc", "limited", "ltd", "llc"
    }:
        words.pop()
    return " ".join(words)


def org_in_text(organization: str, snippet: str) -> bool:
    name = normalize_org(organization)
    text = re.sub(r"[^\w\s]", " ", snippet.casefold())
    return bool(name and re.search(r"(?<!\w)" + re.escape(name) + r"(?!\w)", text))


def resolve(research: Research, extraction: Extraction, excluded: list[str]):
    evidence = {}
    urls = set()
    for item in research.evidence:
        url = safe_url(item.url)
        if not url or url in urls or EXCLUDED.search(item.snippet + " " + item.title):
            continue
        evidence[item.id] = item.model_copy(update={"url": url})
        urls.add(url)
    chosen = None
    confidence = "organization_only"

    def normalize(s):
        return " ".join(s.casefold().split())

    for c in sorted(research.candidates, key=lambda x: x.score, reverse=True):
        if not extraction.name.normalized.strip():
            break
        if c.id in excluded or normalize(c.name) != normalize(extraction.name.normalized):
            continue
        if normalize_org(c.organization) != normalize_org(extraction.organization.normalized):
            continue
        supporting = [
            evidence[x]
            for x in c.source_ids
            if x in evidence
            and evidence[x].subject == "person"
            and normalize(c.name) in normalize(evidence[x].title + " " + evidence[x].snippet)
            and org_in_text(c.organization, evidence[x].title + " " + evidence[x].snippet)
        ]
        if not supporting or c.score < 0.55:
            continue
        strong = any(x.reliability == "primary" for x in supporting)
        independent = len({domain(x.url) for x in supporting}) >= 2
        role_supported = c.role and sum(
            normalize(c.role) in normalize(x.title + " " + x.snippet) for x in supporting
        ) >= 2
        if independent and role_supported and c.score >= 0.85:
            confidence = "high"
        elif strong:
            confidence = "medium"
        else:
            continue
        chosen = c
        allowed = set(c.source_ids)
        evidence = {k: v for k, v in evidence.items() if v.subject == "organization" or k in allowed}
        break
    if not chosen:
        evidence = {k: v for k, v in evidence.items() if v.subject == "organization"}
    return chosen, confidence, list(evidence.values())


def validate_brief(brief: Brief, evidence: list[Evidence], confidence: str) -> list[str]:
    problems = []
    ids = {x.id for x in evidence}
    claims = [brief.headline, *brief.summary, *brief.interests, *brief.starters]
    if brief.organization_snapshot:
        claims.append(brief.organization_snapshot)
    if any(not c.source_ids or not set(c.source_ids) <= ids for c in claims):
        problems.append("Unknown evidence references")
    if EXCLUDED.search(brief.model_dump_json()) or INVASIVE.search(brief.model_dump_json()):
        problems.append("Excluded or invasive content")
    if confidence == "organization_only" and (brief.interests or brief.confidence != "organization_only"):
        problems.append("Person claims in organization-only result")
    if brief.confidence != confidence:
        problems.append("Confidence mismatch")
    return problems
