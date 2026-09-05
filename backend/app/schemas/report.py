from __future__ import annotations

from pydantic import BaseModel, Field


class ActionItem(BaseModel):
    title: str
    description: str
    metrics: list[str] = Field(default_factory=list)
    resources: list[str] = Field(default_factory=list)
    deadline: str | None = None


class PhasePlan(BaseModel):
    phase: str  # short|mid|final
    duration_weeks: int
    actions: list[ActionItem] = Field(default_factory=list)


class CareerReport(BaseModel):
    report_id: str
    student_id: str
    target_jobs: list[dict] = Field(default_factory=list)

    summary: str
    fit_analysis: dict = Field(default_factory=dict)
    student_snapshot: dict = Field(default_factory=dict)
    career_path: dict = Field(default_factory=dict)
    action_plan: list[PhasePlan] = Field(default_factory=list)
    evaluation: dict = Field(default_factory=dict)
    knowledge_references: list[dict] = Field(default_factory=list)

    markdown: str
