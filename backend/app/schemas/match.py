from __future__ import annotations

from pydantic import BaseModel, Field


class EvidenceSpan(BaseModel):
    doc_type: str  # job|resume|student
    section: str | None = None
    text: str
    offset: tuple[int, int] | None = None


class MatchedSkill(BaseModel):
    skill_id: str | None = None
    name: str
    match: float  # 0|0.5|1
    importance: str | None = None
    confidence: float | None = None
    evidence: EvidenceSpan | None = None


class TransferableSkill(BaseModel):
    from_skill: str
    to_skill: str
    reason: str
    confidence: float


class DimensionBasic(BaseModel):
    score: float
    passed_gates: bool
    details: list[dict] = Field(default_factory=list)


class DimensionSkills(BaseModel):
    score: float
    matched: list[MatchedSkill] = Field(default_factory=list)
    missing: list[MatchedSkill] = Field(default_factory=list)
    transferable: list[TransferableSkill] = Field(default_factory=list)


class DimensionQualities(BaseModel):
    score: float
    signals: list[dict] = Field(default_factory=list)


class DimensionPotential(BaseModel):
    score: float
    signals: list[dict] = Field(default_factory=list)


class MatchResult(BaseModel):
    student_id: str
    job_id: str
    overall_score: float
    dimension_scores: dict
    weights: dict
    version: str = "score_v1.0"
