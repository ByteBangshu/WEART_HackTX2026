import asyncio
import base64
import json
import random
import time
from dataclasses import dataclass, field
from datetime import date
from urllib.parse import urlsplit

import httpx

from .config import ROOT, Settings
from .domain import Brief, CardField, Evidence, Extraction, Research, Verification
from .safety import normalize_org, official_org_domain, org_in_text, safe_url


class ProviderError(Exception):
    """Sanitized exception; never embeds provider response content."""


class BudgetExceeded(ProviderError):
    pass


class SearchDisabled(ProviderError):
    pass


def source_key(url: str) -> tuple[str, str]:
    parsed = urlsplit(url)
    host = (parsed.hostname or "").removeprefix("www.")
    return host, parsed.path.rstrip("/") or "/"


@dataclass
class Ledger:
    cap: float
    day: date = field(default_factory=date.today)
    reserved: float = 0

    def reserve(self, cost):
        if self.day != date.today():
            self.day, self.reserved = date.today(), 0
        if self.cap and self.reserved + cost > self.cap:
            raise BudgetExceeded("Daily request budget exhausted")
        self.reserved += cost


@dataclass
class Budget:
    cap: float
    ledger: Ledger
    reserved: float = 0
    input_tokens: int = 0
    output_tokens: int = 0
    searches: int = 0
    estimated_cost: float = 0

    def reserve(self, cost):
        if self.cap and self.reserved + cost > self.cap:
            raise BudgetExceeded("Job request budget exhausted")
        self.ledger.reserve(cost)
        self.reserved += cost

    def usage(self, response, reservation=0.0):
        usage = response.get("usage", {})
        i, o = int(usage.get("input_tokens", 0)), int(usage.get("output_tokens", 0))
        searches = sum(x.get("type") == "web_search_call" for x in response.get("output", []))
        self.input_tokens += i
        self.output_tokens += o
        self.searches += searches
        actual = i * 1.25e-6 + o * 4.25e-6 + searches * 0.0025
        self.estimated_cost += actual
        if "input_tokens" in usage and "output_tokens" in usage:
            # Replace the pessimistic admission estimate with reported usage.
            adjustment = actual - reservation
            self.reserved = max(0.0, self.reserved + adjustment)
            self.ledger.reserved = max(0.0, self.ledger.reserved + adjustment)


class MockAdapter:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def pause(self):
        await asyncio.sleep(self.settings.mock_delay)

    async def extract(self, image, scenario, budget):
        await self.pause()

        def f(s):
            return CardField(text=s, normalized=s, confidence=0.98)

        return Extraction(
            legibility="good",
            name=f("Avery Chen"),
            organization=f("Example Robotics"),
            job_title=f("Robotics Engineer"),
            event=f("Fictional Demo Conference"),
            ambiguity=["mock:" + scenario],
        )

    async def research(self, extraction, excluded, budget):
        await self.pause()
        data = json.loads((ROOT / "host/fixtures/research.json").read_text(encoding="utf-8"))
        if (
            extraction.name.normalized != "Avery Chen"
            or extraction.organization.normalized != "Example Robotics"
        ):
            return Research(candidates=[], evidence=[], risk_flags=["No fixture for corrected identity"])
        if "mock:organization" in extraction.ambiguity or excluded:
            data["candidates"] = []
        if "mock:missing" in extraction.ambiguity:
            data["candidates"], data["evidence"] = [], []
        return Research.model_validate(data)

    async def synthesize(self, context, budget, repair=False):
        await self.pause()
        person = context["confidence"] != "organization_only"
        return Brief.model_validate(
            {
                "headline": {
                    "text": "Avery Chen · Robotics Engineer" if person else "Example Robotics",
                    "source_ids": ["e1" if person else "e3"],
                },
                "summary": [
                    {
                        "text": "Avery develops dependable robot control systems and shares practical testing methods."
                        if person
                        else "Example Robotics develops tools for dependable robot testing.",
                        "source_ids": ["e1" if person else "e3"],
                    }
                ],
                "interests": [
                    {
                        "text": "Reliable robotics — documented in their engineering work.",
                        "source_ids": ["e1"],
                    }
                ]
                if person
                else [],
                "starters": [
                    {
                        "text": "What is the hardest part of testing a robot outside the lab?",
                        "why": "Connects to the published testing work.",
                        "source_ids": ["e1" if person else "e3"],
                    },
                    {
                        "text": "What has your team learned from making robot testing more repeatable?",
                        "why": "Invites a professional perspective on the organization’s work.",
                        "source_ids": ["e3"],
                    },
                    {
                        "text": "Which part of that work would you most like to explore next?",
                        "why": "A light follow-up to the previous work-related question.",
                        "source_ids": ["e3"],
                    },
                ],
                "organization_snapshot": {
                    "text": "Example Robotics builds robot testing tools. This organization and all demo sources are fictional.",
                    "source_ids": ["e3"],
                },
                "confidence": context["confidence"],
                "caveats": ["Offline mock fixture. Not a real person or verified research."],
                "could_not_verify": [] if person else ["Individual identity"],
                "device_lines": [
                    "Avery Chen" if person else "Organization only",
                    "Example Robotics",
                    "Ask about reliable robot testing",
                ],
            }
        )

    async def verify(self, brief, context, budget):
        await self.pause()
        return Verification(verdict="pass", reasons=[])

    async def close(self):
        pass


def strict_schema(model):
    schema = model.model_json_schema()

    def walk(value):
        if isinstance(value, dict):
            if value.get("type") == "object":
                value["additionalProperties"] = False
                value["required"] = list(value.get("properties", {}))
            value.pop("default", None)
            for v in value.values():
                walk(v)
        elif isinstance(value, list):
            for v in value:
                walk(v)

    walk(schema)
    return schema


class MetaMuseAdapter:
    def __init__(self, settings: Settings, transport=None):
        self.settings = settings
        self.client = httpx.AsyncClient(
            base_url="https://api.meta.ai/v1/",
            timeout=settings.stage_timeout,
            follow_redirects=False,
            transport=transport,
            headers={"Authorization": "Bearer " + settings.api_key},
        )
        self.failures = 0
        self.open_until = 0.0

    async def call(self, stage, model, data, budget, image=None, search=False):
        if time.monotonic() < self.open_until:
            raise ProviderError("Provider circuit temporarily open")
        if search and not self.settings.allow_unbounded_search:
            raise SearchDisabled(
                "Live search requires explicit acceptance of its unbounded provider-side query cost"
            )
        if search and self.settings.max_search_calls is not None and budget.searches >= self.settings.max_search_calls:
            raise BudgetExceeded("Search budget exhausted")
        instructions = (
            (ROOT / "host/prompts/shared.txt").read_text()
            + "\n"
            + (ROOT / f"host/prompts/{stage}.txt").read_text()
        )
        content = [
            {
                "type": "input_text",
                "text": "UNTRUSTED_DATA_BEGIN\n"
                + json.dumps(data, ensure_ascii=False)
                + "\nUNTRUSTED_DATA_END",
            }
        ]
        if image:
            content.append(
                {
                    "type": "input_image",
                    "image_url": "data:image/jpeg;base64," + base64.b64encode(image).decode(),
                }
            )
        payload = {
            "model": self.settings.model,
            "store": False,
            "instructions": instructions,
            "input": [{"role": "user", "content": content}],
            "max_output_tokens": 4000,
            "reasoning": {"effort": "low" if stage == "extract" else "medium"},
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": model.__name__,
                    "schema": strict_schema(model),
                    "strict": True,
                }
            },
        }
        if search:
            payload.update(
                tools=[{"type": "web_search", "search_context_size": "medium"}],
                include=["web_search_call.results"],
            )
            if self.settings.max_search_calls is not None:
                payload["max_tool_calls"] = self.settings.max_search_calls
        for attempt in range(2):
            # Conservative admission reservation. Built-in search may exceed its reserved estimate;
            # live search is disabled by default and is never represented as a hard billing cap.
            reserve = (
                len(instructions.encode()) + len(json.dumps(data).encode()) + (15000 if image else 0)
            ) * 1.25e-6 + 4000 * 4.25e-6
            reserve += 0.0025 * (self.settings.max_search_calls or 0) if search else 0
            budget.reserve(reserve)
            try:
                response = await self.client.post("responses", json=payload)
                if response.status_code == 429 or response.status_code >= 500:
                    raise ProviderError("Provider temporarily unavailable")
                if response.status_code >= 400:
                    raise ProviderError("Provider rejected the request configuration")
                body = response.json()
                budget.usage(body, reserve)
                if body.get("status") != "completed":
                    raise ValueError("Incomplete model output")
                pieces = [
                    p["text"]
                    for item in body.get("output", [])
                    if item.get("type") == "message" and item.get("phase") != "commentary"
                    for p in item.get("content", [])
                    if p.get("type") == "output_text"
                ]
                parsed = model.model_validate_json("".join(pieces))
                if isinstance(parsed, Research):
                    # Model-authored URLs alone are insufficient. Retain actual retrieved snippets.
                    calls = [
                        item for item in body.get("output", [])
                        if item.get("type") == "web_search_call"
                    ]
                    if not calls and attempt == 0:
                        content[0]["text"] += (
                            "\nThis is a source verification request. Run live web search for the exact "
                            "name and organization before returning any candidate or evidence."
                        )
                        continue
                    sources: dict[str, dict] = {}
                    canonical: dict[tuple[str, str], str | None] = {}
                    for item in calls:
                        for hit in item.get("results") or []:
                            url = safe_url(hit.get("url", ""))
                            if not url or not (hit.get("snippet") or hit.get("title")):
                                continue
                            sources[url] = hit
                            key = source_key(url)
                            if key in canonical and canonical[key] != url:
                                canonical[key] = None
                            elif key not in canonical:
                                canonical[key] = url
                    grounded = []
                    title_only = False
                    for e in parsed.evidence:
                        url = safe_url(e.url)
                        matched_url = url if url in sources else canonical.get(source_key(url)) if url else None
                        hit = sources.get(matched_url) if matched_url else None
                        if hit:
                            title = str(hit.get("title") or "")[:250]
                            snippet = str(hit.get("snippet") or "")[:1600]
                            if not snippet:
                                title_only = True
                                snippet = "Search result title: " + title
                            grounded.append(
                                e.model_copy(
                                    update={
                                        "url": matched_url,
                                        "title": title,
                                        "snippet": snippet,
                                    }
                                )
                            )
                    card = data.get("card", {})
                    name = card.get("name", {}).get("normalized", "")
                    organization = card.get("organization", {}).get("normalized", "")
                    fallback_ids = []
                    original_grounded_ids = {e.id for e in grounded}
                    person_corroborated = any(
                        e.subject == "person"
                        and org_in_text(name, e.title + " " + e.snippet)
                        and (
                            org_in_text(organization, e.title + " " + e.snippet)
                            or official_org_domain(organization, e.url)
                        )
                        for e in grounded
                    )
                    if name and organization and not person_corroborated:
                        used = set(original_grounded_ids)
                        for url, hit in sources.items():
                            title = str(hit.get("title") or "")[:250]
                            snippet = str(hit.get("snippet") or "")[:1600]
                            source_text = title + " " + snippet
                            if not org_in_text(name, source_text) or not (
                                org_in_text(organization, source_text)
                                or official_org_domain(organization, url)
                            ):
                                continue
                            next_id = next(
                                (f"e{n}" for n in range(1, 13) if f"e{n}" not in used),
                                None,
                            )
                            if not next_id:
                                break
                            used.add(next_id)
                            fallback_ids.append(next_id)
                            grounded.append(
                                Evidence(
                                    id=next_id,
                                    url=url,
                                    title=title,
                                    publisher=(urlsplit(url).hostname or "")[:160],
                                    date=None,
                                    category="role",
                                    reliability="primary"
                                    if official_org_domain(organization, url)
                                    else "secondary",
                                    snippet=snippet or "Search result title: " + title,
                                    subject="person",
                                )
                            )
                            if len(grounded) >= 12:
                                break
                    if fallback_ids:
                        for candidate in parsed.candidates:
                            if candidate.name.casefold() == name.casefold() and normalize_org(
                                candidate.organization
                            ) == normalize_org(organization):
                                candidate.source_ids = [
                                    *[sid for sid in candidate.source_ids if sid in original_grounded_ids],
                                    *fallback_ids,
                                ][:12]
                    parsed.evidence = grounded
                    if not calls:
                        parsed._grounding_status = "provider_skipped_web_search"
                    elif not sources:
                        parsed._grounding_status = "web_search_no_source_text"
                    elif not grounded:
                        parsed._grounding_status = "web_search_sources_unmatched"
                    elif fallback_ids:
                        parsed._grounding_status = "raw_result_fallback"
                    elif title_only:
                        parsed._grounding_status = "title_only_grounding"
                self.failures = 0
                return parsed
            except (httpx.HTTPError, ValueError, ProviderError) as exc:
                self.failures += 1
                if self.failures >= 4:
                    self.open_until = time.monotonic() + 30
                if attempt:
                    if isinstance(exc, ProviderError):
                        raise exc
                    raise ProviderError(
                        "Provider request failed or returned invalid structured data"
                    ) from None
                await asyncio.sleep(0.3 + random.random() * 0.4)
        raise ProviderError("Provider unavailable")

    async def extract(self, image, scenario, budget):
        return await self.call("extract", Extraction, {}, budget, image=image)

    async def research(self, extraction, excluded, budget):
        return await self.call(
            "research",
            Research,
            {"card": extraction.model_dump(), "excluded_candidate_ids": excluded},
            budget,
            search=True,
        )

    async def synthesize(self, context, budget, repair=False):
        return await self.call("synthesize", Brief, {**context, "repair_previous_attempt": repair}, budget)

    async def verify(self, brief, context, budget):
        return await self.call(
            "verify", Verification, {"brief": brief.model_dump(), "context": context}, budget
        )

    async def close(self):
        await self.client.aclose()
