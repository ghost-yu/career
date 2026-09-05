import { personalStorageKey } from './personalStorage'
export type ResumeTemplateDraft = {
  student_id?: string
  job_id?: string
  target_title?: string
  source_filename?: string | null
  llm_used?: boolean
  generated_at: string
  resume_markdown: string
  targeted_summary?: string
  highlighted_keywords?: string[]
  missing_keywords?: string[]
  risk_notes?: string[]
  cover_letter?: string
}

const DRAFT_PREFIX = 'resume_template_draft_'

function randomSuffix() {
  return Math.random().toString(36).slice(2, 8)
}

export function saveResumeTemplateDraft(draft: ResumeTemplateDraft): string {
  const key = `${personalStorageKey(DRAFT_PREFIX)}:${Date.now()}_${randomSuffix()}`
  window.localStorage.setItem(key, JSON.stringify(draft))
  return key
}

export function loadResumeTemplateDraft(key: string): ResumeTemplateDraft | null {
  if (!key || !key.startsWith(`${personalStorageKey(DRAFT_PREFIX)}:`)) {
    return null
  }
  const raw = window.localStorage.getItem(key)
  if (!raw) {
    return null
  }
  try {
    return JSON.parse(raw) as ResumeTemplateDraft
  } catch {
    return null
  }
}
