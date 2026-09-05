from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class StudentCreate(BaseModel):
    student_id: str
    name: str | None = None


class StudentOut(BaseModel):
    student_id: str
    name: str | None = None


class StudentSkill(BaseModel):
    skill_id: str | None = None
    mention: str
    level: str | None = None
    proficiency: str | None = None
    proficiency_label: str | None = None
    proficiency_score: float | None = None
    proficiency_source: str | None = None
    evidence: str | None = None
    source_section: str | None = None
    confidence: float | None = None
    mapping_method: str | None = None


class StudentSoftSkill(BaseModel):
    soft_skill_id: str | None = None
    name: str
    evidence: str | None = None
    strength: str | None = None  # strong|weak
    source_section: str | None = None
    confidence: float | None = None
    mapping_method: str | None = None


class StudentCertificate(BaseModel):
    certificate_id: str | None = None
    name: str
    evidence: str | None = None
    source_section: str | None = None
    confidence: float | None = None
    mapping_method: str | None = None


class StudentExperience(BaseModel):
    internships: int = 0
    projects: int = 0
    awards: int = 0
    publications: int = 0
    open_source: int = 0
    leadership: int = 0


class StudentPreferences(BaseModel):
    preferred_locations: list[str] = Field(default_factory=list)
    preferred_job_families: list[str] = Field(default_factory=list)
    target_salary_min: int | None = None
    target_salary_max: int | None = None
    notes: str | None = None


class StudentProfile(BaseModel):
    student_id: str
    mbti_type: str | None = None
    mbti_source: str | None = None
    hard_skills: list[StudentSkill] = Field(default_factory=list)
    soft_skills: list[StudentSoftSkill] = Field(default_factory=list)
    certificates: list[StudentCertificate] = Field(default_factory=list)
    experience: StudentExperience = Field(default_factory=StudentExperience)
    preferences: StudentPreferences = Field(default_factory=StudentPreferences)
    completeness_score: float | None = None
    competitiveness_score: float | None = None
    profile_notes: str | None = None
    extraction_meta: dict[str, Any] = Field(default_factory=dict)
