import asyncio
import base64
import json
import random
import time
from dataclasses import dataclass, field
from datetime import date

import httpx

from .config import ROOT, Settings
from .domain import Brief, CardField, Classification, Extraction, Research, Verification
from .safety import safe_url


class ProviderError(Exception):
    """Sanitized exception; never embeds provider response content."""


class BudgetExceeded(ProviderError):
    pass


@dataclass
class Ledger:
    cap: float
    day: date = field(default_factory=date.today)
    reserved: float = 0

    def reserve(self, cost):
        if self.day != date.today():
            self.day, self.reserved = date.today(), 0
        if self.reserved + cost > self.cap:
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
        if self.reserved + cost > self.cap:
            raise BudgetExceeded("Job request budget exhausted")
        self.ledger.reserve(cost)
        self.reserved += cost

    def usage(self, response):
        usage = response.get("usage", {})
        i, o = int(usage.get("input_tokens", 0)), int(usage.get("output_tokens", 0))
        searches = sum(x.get("type") == "web_search_call" for x in response.get("output", []))
        self.input_tokens += i
        self.output_tokens += o
        self.searches += searches
        self.estimated_cost += i * 1.25e-6 + o * 4.25e-6 + searches * 0.0025


class MockAdapter:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def pause(self):
        await asyncio.sleep(self.settings.mock_delay)

    async def classify(self, image, scenario, budget):
        await self.pause()
        return Classification(
            card_type="government_id" if scenario == "rejected" else "conference_badge", confidence=0.99
        )

    async def extract(self, image, scenario, budget):
        await self.pause()

        def f(s):
            return CardField(text=s, normalized=s, confidence=0.98)

        return Extraction(
            card_type="conference_badge",
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
            raise ProviderError(
                "Live search requires explicit acceptance of its unbounded provider-side query cost"
            )
        if search and budget.searches >= self.settings.max_search_calls:
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
            "reasoning": {"effort": "low" if stage in {"classify", "extract"} else "medium"},
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
        for attempt in range(2):
            # Conservative admission reservation. Built-in search may exceed its reserved estimate;
            # live search is disabled by default and is never represented as a hard billing cap.
            reserve = (
                len(instructions.encode()) + len(json.dumps(data).encode()) + (15000 if image else 0)
            ) * 1.25e-6 + 4000 * 4.25e-6
            reserve += 0.0025 * self.settings.max_search_calls if search else 0
            budget.reserve(reserve)
            try:
                response = await self.client.post("responses", json=payload)
                if response.status_code == 429 or response.status_code >= 500:
                    raise ProviderError("Provider temporarily unavailable")
                if response.status_code >= 400:
                    raise ProviderError("Provider rejected the request configuration")
                body = response.json()
                budget.usage(body)
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
                    sources = {
                        safe_url(x.get("url", "")): x
                        for item in body.get("output", [])
                        if item.get("type") == "web_search_call"
                        for x in item.get("results", [])
                    }
                    grounded = []
                    for e in parsed.evidence:
                        hit = sources.get(safe_url(e.url))
                        if hit and hit.get("snippet"):
                            grounded.append(e.model_copy(update={"snippet": str(hit["snippet"])[:1600]}))
                    parsed.evidence = grounded
                self.failures = 0
                return parsed
            except (httpx.HTTPError, ValueError, ProviderError):
                self.failures += 1
                if self.failures >= 4:
                    self.open_until = time.monotonic() + 30
                if attempt:
                    raise ProviderError(
                        "Provider request failed or returned invalid structured data"
                    ) from None
                await asyncio.sleep(0.3 + random.random() * 0.4)
        raise ProviderError("Provider unavailable")

    async def classify(self, image, scenario, budget):
        return await self.call("classify", Classification, {}, budget, image=image)

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
