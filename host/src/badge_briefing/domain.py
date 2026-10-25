from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", str_max_length=4000)


class State(StrEnum):
    RECEIVED = "RECEIVED"
    GATED = "GATED"
    EXTRACTING = "EXTRACTING"
    AWAITING_CONFIRMATION = "AWAITING_CONFIRMATION"
    RESOLVING = "RESOLVING"
    RESEARCHING = "RESEARCHING"
    SYNTHESIZING = "SYNTHESIZING"
    VERIFYING = "VERIFYING"
    COMPLETE = "COMPLETE"
    COMPLETE_ORG_ONLY = "COMPLETE_ORG_ONLY"
    RETAKE = "RETAKE"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


TERMINAL = {
    State.COMPLETE,
    State.COMPLETE_ORG_ONLY,
    State.RETAKE,
    State.FAILED,
    State.CANCELLED,
    State.EXPIRED,
}
class CardField(Model):
    text: str = Field(max_length=160)
    normalized: str = Field(max_length=160)
    confidence: float = Field(ge=0, le=1)


class Extraction(Model):
    legibility: Literal["good", "partial", "unreadable"]
    name: CardField
    organization: CardField
    job_title: CardField
    event: CardField
    ambiguity: list[str] = Field(max_length=6)


class Evidence(Model):
    id: str = Field(pattern=r"^e[0-9]{1,3}$")
    url: str = Field(max_length=2048)
    title: str = Field(max_length=250)
    publisher: str = Field(max_length=160)
    date: str | None
    category: Literal[
        "role", "talk", "publication", "open_source", "interview", "organization", "professional_interest"
    ]
    reliability: Literal["primary", "secondary"]
    snippet: str = Field(max_length=1600)
    subject: Literal["person", "organization"]


class Candidate(Model):
    id: str = Field(max_length=80)
    name: str = Field(max_length=160)
    organization: str = Field(max_length=160)
    role: str = Field(max_length=160)
    source_ids: list[str] = Field(max_length=12)
    score: float = Field(ge=0, le=1)
    organization_corroborated: bool
    role_corroborated: bool


class Research(Model):
    candidates: list[Candidate] = Field(max_length=6)
    evidence: list[Evidence] = Field(max_length=12)
    risk_flags: list[str] = Field(max_length=8)


class Claim(Model):
    text: str = Field(max_length=450)
    source_ids: list[str] = Field(max_length=6)


class Starter(Claim):
    why: str = Field(max_length=250)

    @field_validator("text")
    @classmethod
    def short(cls, text):
        if len(text.split()) > 25:
            raise ValueError("starter exceeds 25 words")
        return text


class Brief(Model):
    headline: Claim
    summary: list[Claim] = Field(max_length=4)
    interests: list[Claim] = Field(max_length=5)
    starters: list[Starter] = Field(max_length=5)
    organization_snapshot: Claim | None
    confidence: Literal["high", "medium", "organization_only"]
    caveats: list[str] = Field(max_length=8)
    could_not_verify: list[str] = Field(max_length=8)
    device_lines: list[str] = Field(max_length=3)

    @model_validator(mode="after")
    def lengths(self):
        if sum(len(x.text.split()) for x in self.summary) > 60:
            raise ValueError("summary exceeds 60 words")
        if self.organization_snapshot and len(self.organization_snapshot.text.split()) > 30:
            raise ValueError("organization snapshot exceeds 30 words")
        if len("\n".join(self.device_lines)) > 240:
            raise ValueError("device variant exceeds 240 characters")
        return self


class Verification(Model):
    verdict: Literal["pass", "repair", "degrade"]
    reasons: list[str] = Field(max_length=8)


class Correction(Model):
    name: str = Field(max_length=160)
    organization: str = Field(min_length=1, max_length=160)
