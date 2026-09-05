from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class JobIn(BaseModel):
    job_id: str
    title: str
    location: str | None = None
    salary_min: int | None = None
    salary_max: int | None = None
    salary_period: str | None = None
    company_name: str | None = None
    industry: str | None = None
    company_size: str | None = None
    company_type: str | None = None
    job_code: str | None = None
    description: str | None = None
    company_intro: str | None = None
    updated_date: str | None = None
    source_url: str | None = None
    raw: dict[str, Any] | None = None


class JobOut(BaseModel):
    job_id: str
    title: str
    location: str | None = None
    salary_min: int | None = None
    salary_max: int | None = None
    salary_period: str | None = None
    company_name: str | None = None
    industry: str | None = None
    updated_date: str | None = None
    source_url: str | None = None


class SkillMention(BaseModel):
    # Normalized ID (recommended). Filled by the normalization layer.
    skill_id: str | None = None
    mention: str
    importance: Literal["must", "plus", "must_low"] = "must"
    level: str | None = None
    proficiency: str | None = None
    proficiency_label: str | None = None
    proficiency_score: float | None = None
    evidence: str | None = None
    source_section: str | None = None
    confidence: float | None = None
    mapping_method: str | None = None


class SoftSkillMention(BaseModel):
    soft_skill_id: str | None = None
    name: str
    importance: Literal["must", "plus", "must_low"] = "must"
    evidence: str | None = None
    source_section: str | None = None
    confidence: float | None = None
    mapping_method: str | None = None


class CertificateMention(BaseModel):
    certificate_id: str | None = None
    name: str
    importance: Literal["must", "plus", "must_low"] = "plus"
    evidence: str | None = None
    source_section: str | None = None
    confidence: float | None = None
    mapping_method: str | None = None


class BasicRequirements(BaseModel):
    education: str | None = None
    major: list[str] = Field(default_factory=list)
    experience_years_min: int | None = None
    location: list[str] = Field(default_factory=list)


class JobProfile(BaseModel):
    job_id: str
    hard_skills: list[SkillMention] = Field(default_factory=list)
    soft_skills: list[SoftSkillMention] = Field(default_factory=list)
    certificates: list[CertificateMention] = Field(default_factory=list)
    basic_requirements: BasicRequirements = Field(default_factory=BasicRequirements)
    tags: list[str] = Field(default_factory=list)
    job_family: str | None = None
