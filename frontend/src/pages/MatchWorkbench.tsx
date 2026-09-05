import { personalStorageKey } from '../utils/personalStorage'
import React, { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { DislikeOutlined, StarFilled, StarOutlined } from '@ant-design/icons'
import {
  Alert,
  App,
  Button,
  Card,
  Col,
  Descriptions,
  Drawer,
  Input,
  List,
  Progress,
  Row,
  Select,
  Slider,
  Space,
  Switch,
  Table,
  Tag,
  Typography
} from 'antd'
import { api } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { familyLabel, familyOptions, levelLabel } from '../constants/labels'
import { presentRoleName, presentStudentOption } from '../utils/present'

const { Text, Title } = Typography

const strategyOptions = [
  { label: '均衡', value: 'balanced' },
  { label: '技能优先', value: 'skill_first' },
  { label: '地点优先', value: 'location_first' },
  { label: '薪资优先', value: 'salary_first' }
]

const strategyLabelMap: Record<string, string> = {
  balanced: '均衡',
  skill_first: '技能优先',
  location_first: '地点优先',
  salary_first: '薪资优先'
}

const recommendModeOptions = [
  { label: '匹配岗位', value: 'jobs' },
  { label: '匹配角色', value: 'roles' }
]

const recommendModeLabelMap: Record<string, string> = {
  jobs: '匹配岗位',
  roles: '匹配角色'
}

const MATCH_WORKBENCH_STATE_KEY = 'match_workbench_state_v1'

type MatchWorkbenchPersistedState = {
  studentId?: string
  recommendMode?: 'jobs' | 'roles'
  family?: string
  strategy?: string
  keyword?: string
  location?: string
  locationWeight?: number
  aiRerankEnabled?: boolean
  aiRerankTopN?: number
  aiRerankWeight?: number
  aiRerankDebug?: boolean
  profileSource?: string
  behaviorUsedEvents?: number
  totalCandidates?: number
  items?: any[]
  recommendDiagnostics?: any
  aiRerankDebugPayload?: any
}

function loadPersistedState(): MatchWorkbenchPersistedState | null {
  if (typeof window === 'undefined') return null
  try {
    const raw = window.sessionStorage.getItem(personalStorageKey(MATCH_WORKBENCH_STATE_KEY))
    if (!raw) return null
    const parsed = JSON.parse(raw)
    if (!parsed || typeof parsed !== 'object') return null
    return parsed as MatchWorkbenchPersistedState
  } catch {
    return null
  }
}

const profileSourceLabelMap: Record<string, string> = {
  existing: '已存在画像',
  generated_from_latest_resume: '已从最新简历自动生成画像',
  generated_empty_fallback: '画像缺失，已生成基础兜底画像',
  missing: '画像仍缺失（建议先在学生页生成）'
}

function profileSourceLabel(raw: string | undefined): string {
  const key = String(raw || '').trim()
  return profileSourceLabelMap[key] || '未知画像来源'
}

function relevanceTagColor(value: string): string {
  const v = String(value || '').toLowerCase()
  if (v === 'high') return 'green'
  if (v === 'medium') return 'blue'
  if (v === 'low') return 'orange'
  return 'default'
}

function salaryText(job: any): string {
  const min = Number(job?.salary_min || 0)
  const max = Number(job?.salary_max || 0)
  if (min > 0 || max > 0) {
    if (min > 0 && max > 0) return `${min} - ${max}`
    return String(min || max)
  }
  const raw = String(job?.salary_range || '').trim()
  return raw || '-'
}

function locationMatchTag(row: any) {
  const details = row?.dimension_scores?.basic?.details || []
  const hit = Array.isArray(details)
    ? details.find((it: any) => String(it?.item || '').includes('地点'))
    : null
  const result = String(hit?.result || '').trim()
  if (!result) return <Tag>未设置</Tag>
  if (result === '匹配') return <Tag color="green">同城/可接受</Tag>
  if (result === '不匹配') return <Tag color="orange">地点不匹配</Tag>
  return <Tag>{result}</Tag>
}

export default function MatchWorkbench() {
  const { message } = App.useApp()
  const { canWrite } = useAuth()
  const navigate = useNavigate()
  const persisted = loadPersistedState()
  const [students, setStudents] = useState<any[]>([])
  const [studentId, setStudentId] = useState<string | undefined>(persisted?.studentId)
  const [recommendMode, setRecommendMode] = useState<'jobs' | 'roles'>(persisted?.recommendMode === 'roles' ? 'roles' : 'jobs')
  const [family, setFamily] = useState(String(persisted?.family || ''))
  const [strategy, setStrategy] = useState(String(persisted?.strategy || 'balanced'))
  const [keyword, setKeyword] = useState(String(persisted?.keyword || ''))
  const [location, setLocation] = useState(String(persisted?.location || ''))
  const [locationWeight, setLocationWeight] = useState(Number(persisted?.locationWeight || 1.0))
  const [aiRerankEnabled, setAiRerankEnabled] = useState(Boolean(persisted?.aiRerankEnabled ?? true))
  const [aiRerankTopN, setAiRerankTopN] = useState(Number(persisted?.aiRerankTopN || 20))
  const [aiRerankWeight, setAiRerankWeight] = useState(Number(persisted?.aiRerankWeight || 0.35))
  const [aiRerankDebug, setAiRerankDebug] = useState(Boolean(persisted?.aiRerankDebug ?? true))
  const [aiRerankDebugPayload, setAiRerankDebugPayload] = useState<any>(persisted?.aiRerankDebugPayload || null)
  const [familySelectOptions, setFamilySelectOptions] = useState(familyOptions)
  const [items, setItems] = useState<any[]>(Array.isArray(persisted?.items) ? persisted.items : [])
  const [loading, setLoading] = useState(false)
  const [detail, setDetail] = useState<any>(null)
  const [profileSource, setProfileSource] = useState(String(persisted?.profileSource || ''))
  const [behaviorUsedEvents, setBehaviorUsedEvents] = useState(Number(persisted?.behaviorUsedEvents || 0))
  const [totalCandidates, setTotalCandidates] = useState(Number(persisted?.totalCandidates || 0))
  const [recommendError, setRecommendError] = useState('')
  const [recommendDiagnostics, setRecommendDiagnostics] = useState<any>(persisted?.recommendDiagnostics || null)
  const [jobPreferences, setJobPreferences] = useState<Record<string, string>>({})
  const detailRequestRef = useRef(0)

  const loadStudents = async (keyword: string = '') => {
    const res = await api.get('/students', {
      params: { limit: 200, offset: 0, q: keyword || undefined }
    })
    const list = res.data.items || []
    setStudents(list)
    if (list.length && !studentId) setStudentId(list[0].student_id)
  }

  useEffect(() => {
    void loadStudents()
  }, [])

  const loadJobPreferences = async (targetStudentId: string | undefined = studentId) => {
    const sid = String(targetStudentId || '').trim()
    if (!sid) {
      setJobPreferences({})
      return
    }
    try {
      const res = await api.get(`/match/preferences/${sid}`, { params: { limit: 2000 } })
      const next: Record<string, string> = {}
      for (const item of res.data?.items || []) {
        const jobId = String(item?.job_id || '').trim()
        const preference = String(item?.preference || '').trim().toUpperCase()
        if (jobId && preference) next[jobId] = preference
      }
      setJobPreferences(next)
    } catch {
      setJobPreferences({})
    }
  }

  useEffect(() => {
    void loadJobPreferences(studentId)
  }, [studentId])

  useEffect(() => {
    const loadFamilies = async () => {
      try {
        const res = await api.get('/roles', { params: { limit: 5000, offset: 0 } })
        const families = Array.from(
          new Set<string>(
            (res.data?.items || [])
              .map((item: any) => String(item?.job_family || '').trim())
              .filter(Boolean)
          )
        )
        if (!families.length) {
          setFamilySelectOptions(familyOptions)
          return
        }
        setFamilySelectOptions([
          { label: '全部', value: '' },
          ...families.map((f) => ({ label: familyLabel(f), value: f })),
        ])
      } catch {
        setFamilySelectOptions(familyOptions)
      }
    }
    void loadFamilies()
  }, [])

  useEffect(() => {
    if (typeof window === 'undefined') return
    const snapshot: MatchWorkbenchPersistedState = {
      studentId,
      recommendMode,
      family,
      strategy,
      keyword,
      location,
      locationWeight,
      aiRerankEnabled,
      aiRerankTopN,
      aiRerankWeight,
      aiRerankDebug,
      profileSource,
      behaviorUsedEvents,
      totalCandidates,
      items,
      recommendDiagnostics,
      aiRerankDebugPayload,
    }
    try {
      window.sessionStorage.setItem(personalStorageKey(MATCH_WORKBENCH_STATE_KEY), JSON.stringify(snapshot))
    } catch {
      // ignore persistence failures
    }
  }, [
    studentId,
    recommendMode,
    family,
    strategy,
    keyword,
    location,
    locationWeight,
    aiRerankEnabled,
    aiRerankTopN,
    aiRerankWeight,
    aiRerankDebug,
    profileSource,
    behaviorUsedEvents,
    totalCandidates,
    items,
    recommendDiagnostics,
    aiRerankDebugPayload,
  ])

  const recommend = async () => {
    if (!studentId) return
    setLoading(true)
    setRecommendError('')
    setRecommendDiagnostics(null)
    setAiRerankDebugPayload(null)
    try {
      const endpoint = recommendMode === 'jobs' ? '/match/recommend_jobs' : '/match/recommend_roles'
      const res = await api.post(endpoint, {
        student_id: studentId,
        engine: recommendMode === 'jobs' ? 'g_rank' : undefined,
        top_k: 12,
        strategy,
        job_family: family || undefined,
        q: keyword || undefined,
        location: recommendMode === 'jobs' ? (location || undefined) : undefined,
        location_weight: locationWeight,
        ai_rerank_enabled: recommendMode === 'jobs' ? aiRerankEnabled : undefined,
        ai_rerank_top_n: recommendMode === 'jobs' ? aiRerankTopN : undefined,
        ai_rerank_weight: recommendMode === 'jobs' ? aiRerankWeight : undefined,
        ai_rerank_debug: recommendMode === 'jobs' ? aiRerankDebug : undefined,
        semantic_enabled: recommendMode === 'jobs' ? true : undefined,
        bge_rerank_enabled: recommendMode === 'jobs' ? aiRerankEnabled : undefined,
        bge_rerank_top_n: recommendMode === 'jobs' ? aiRerankTopN : undefined,
        bge_rerank_weight: recommendMode === 'jobs' ? Math.min(0.45, aiRerankWeight) : undefined,
      })
      const rows = Array.isArray(res.data?.items) ? res.data.items : []
      const diag = recommendMode === 'jobs'
        ? (res.data || {})
        : (res.data?.diagnostics || {})
      setItems(rows)
      setProfileSource(String(res.data?.profile_source || ''))
      setBehaviorUsedEvents(Number(res.data?.behavior_used_events || res.data?.diagnostics?.behavior_used_events || 0))
      setTotalCandidates(Number(res.data?.total_candidates || res.data?.jobs_total || rows.length))
      setRecommendDiagnostics(diag)
      setAiRerankDebugPayload(recommendMode === 'jobs' ? (res.data?.ai_rerank_debug_payload || null) : null)
      if (!rows.length) {
        let reason = '当前筛选条件下没有返回可匹配结果，建议放宽筛选条件。'
        if (recommendMode === 'jobs') {
          const jobsTotal = Number(diag?.jobs_total || 0)
          const scoringPool = Number(diag?.jobs_scoring_pool || 0)
          if (jobsTotal === 0) {
            reason = '当前筛选条件命中岗位数为 0（多半是方向/关键词过滤过严）。'
          } else if (scoringPool === 0) {
            reason = '筛选命中岗位后无可评分候选，建议放宽关键词或关闭严格过滤。'
          }
        } else {
          const roleTotal = Number(diag?.roles_total || 0)
          const withoutMembers = Number(diag?.roles_without_members || 0)
          const scored = Number(diag?.roles_scored || 0)
          const scoreFailed = Number(diag?.roles_score_failed || 0)
          if (roleTotal === 0) {
            reason = '当前筛选条件命中角色数为 0（多半是方向/关键词过滤过严）。'
          } else if (scored === 0 && withoutMembers > 0) {
            reason = '筛选命中了一些角色，但这些角色没有可评分的成员岗位。'
          } else if (scored === 0 && scoreFailed > 0) {
            reason = '筛选命中角色后评分全部失败，通常是代表岗位缺画像或数据不完整。'
          }
        }
        message.warning(reason)
      }
      if (canWrite) {
        void api.post('/match/events', {
          student_id: studentId,
          event_type: 'SEARCH',
          source: 'match_workbench',
          meta: {
            strategy,
            family,
            keyword,
            location,
            location_weight: locationWeight,
            mode: recommendMode,
            ai_rerank_enabled: aiRerankEnabled,
            ai_rerank_top_n: aiRerankTopN,
            ai_rerank_weight: aiRerankWeight,
            ai_rerank_debug: aiRerankDebug,
          }
        }).catch(() => undefined)
      }
    } catch (e: any) {
      setItems([])
      setRecommendError(String(e?.response?.data?.detail || e?.message || '推荐失败'))
    } finally {
      setLoading(false)
    }
  }

  const openDetail = async (row: any) => {
    if (!studentId) {
      message.warning('请先选择学生，再查看岗位详情。')
      return
    }
    const isRoleMode = recommendMode === 'roles'
    const currentRequestId = detailRequestRef.current + 1
    detailRequestRef.current = currentRequestId
    let scoreData: any = {
      student_id: studentId,
      job_id: row?.job_id || row?.representative_job_id,
      overall_score: Number(row?.overall_score || 0),
      dimension_scores: row?.dimension_scores || {},
      semantic_review: null,
      ai_analysis: null,
    }
    setDetail({
      ...row,
      score: scoreData,
      recommendMode,
      job_detail: row,
      job_profile: null,
      detail_loading: true,
      ai_analysis_loading: false,
      ai_analysis_error: '',
    })
    const scoreRequest = canWrite
      ? (() => {
          const payload = isRoleMode
            ? { student_id: studentId, role_id: row.role_id, use_semantic_review: false }
            : {
                student_id: studentId,
                job_id: row.job_id,
                include_ai_analysis: false,
                use_semantic_review: false,
              }
          const endpoint = isRoleMode ? '/match/score_role' : '/match/score'
          return api.post(endpoint, payload)
        })()
      : Promise.resolve(null)
    const jobRequest = !isRoleMode && row?.job_id
      ? api.get(`/jobs/${row.job_id}`)
      : Promise.resolve(null)
    const [scoreRes, jobRes] = await Promise.allSettled([scoreRequest, jobRequest])
    if (scoreRes.status === 'fulfilled' && scoreRes.value?.data) {
      if (scoreRes.value.data?.error) {
        message.warning(`评分失败，已展示基础详情：${String(scoreRes.value.data.error)}`)
      } else {
        scoreData = scoreRes.value.data
      }
    } else if (scoreRes.status === 'rejected') {
      message.warning(`评分请求异常，已展示基础详情：${String(scoreRes.reason?.message || 'unknown_error')}`)
    }
    let jobDetail: any = null
    let jobProfile: any = null
    if (jobRes.status === 'fulfilled' && jobRes.value?.data) {
      jobDetail = jobRes.value.data?.job || null
      jobProfile = jobRes.value.data?.profile?.profile || null
    }
    if (currentRequestId !== detailRequestRef.current) {
      return
    }
    setDetail((prev: any) => {
      if (!prev) return prev
      return {
        ...prev,
        ...row,
        score: scoreData,
        recommendMode,
        job_detail: jobDetail || row,
        job_profile: jobProfile || null,
        detail_loading: false,
        ai_analysis_loading: canWrite && !isRoleMode && !!(row?.job_id || row?.representative_job_id),
        ai_analysis_error: '',
      }
    })
    if (canWrite && !isRoleMode && (row?.job_id || row?.representative_job_id)) {
      const analysisJobId = row.job_id || row.representative_job_id
      void (async () => {
        try {
          const analysisRes = await api.post('/match/analysis', {
            student_id: studentId,
            job_id: analysisJobId,
            score_result: scoreData,
            use_cache: false,
            use_semantic_review: false,
          })
          if (currentRequestId !== detailRequestRef.current) return
          const aiAnalysis = analysisRes?.data?.ai_analysis || null
          setDetail((prev: any) => {
            if (!prev) return prev
            return {
              ...prev,
              score: {
                ...(prev.score || {}),
                ai_analysis: aiAnalysis,
              },
              ai_analysis_loading: false,
              ai_analysis_error: aiAnalysis ? '' : 'AI诊断未返回内容',
            }
          })
        } catch (e: any) {
          if (currentRequestId !== detailRequestRef.current) return
          setDetail((prev: any) => {
            if (!prev) return prev
            return {
              ...prev,
              ai_analysis_loading: false,
              ai_analysis_error: String(e?.response?.data?.detail || e?.message || 'AI诊断请求失败'),
            }
          })
        }
      })()
    }
    if (canWrite) {
      void api.post('/match/events', {
        student_id: studentId,
        event_type: isRoleMode ? 'VIEW_ROLE' : 'VIEW_JOB',
        role_id: row.role_id,
        job_id: row.job_id || row.representative_job_id,
        source: 'match_workbench',
        meta: {
          strategy,
          family,
          keyword,
          location,
          location_weight: locationWeight,
          mode: recommendMode,
          ai_rerank_enabled: aiRerankEnabled,
          ai_rerank_top_n: aiRerankTopN,
          ai_rerank_weight: aiRerankWeight,
          ai_rerank_debug: aiRerankDebug,
        }
      }).catch(() => undefined)
    }
  }

  const preferenceOf = (row: any): string => {
    const jobId = String(row?.job_id || '').trim()
    return String((jobId && jobPreferences[jobId]) || row?.user_preference || '').trim().toUpperCase()
  }

  const updatePreferenceState = (jobId: string, preference: string) => {
    setJobPreferences((prev) => {
      const next = { ...prev }
      if (preference) next[jobId] = preference
      else delete next[jobId]
      return next
    })
    setItems((prev) => {
      if (preference === 'DISMISS') {
        return prev.filter((item) => String(item?.job_id || '') !== jobId)
      }
      return prev.map((item) => {
        if (String(item?.job_id || '') !== jobId) return item
        return {
          ...item,
          user_preference: preference || null,
          is_favorite: preference === 'FAVORITE',
          is_dismissed: preference === 'DISMISS',
        }
      })
    })
    setDetail((prev: any) => {
      if (!prev || String(prev?.job_id || '') !== jobId) return prev
      return {
        ...prev,
        user_preference: preference || null,
        is_favorite: preference === 'FAVORITE',
        is_dismissed: preference === 'DISMISS',
      }
    })
  }

  const setJobPreference = async (row: any, preference: 'FAVORITE' | 'DISMISS') => {
    const jobId = String(row?.job_id || '').trim()
    if (!studentId || !jobId) {
      message.warning('请先选择学生和岗位。')
      return
    }
    if (!canWrite) {
      message.warning('只读账号不能写入收藏或不感兴趣。')
      return
    }
    const current = preferenceOf(row)
    const nextPreference = current === preference ? 'CLEAR' : preference
    try {
      await api.post('/match/preferences', {
        student_id: studentId,
        job_id: jobId,
        preference: nextPreference,
        source: 'match_workbench',
        meta: {
          title: row?.title,
          company_name: row?.company_name,
          strategy,
          family,
          keyword,
          location,
        },
      })
      updatePreferenceState(jobId, nextPreference === 'CLEAR' ? '' : preference)
      if (nextPreference === 'CLEAR') message.success('已取消标记')
      else if (preference === 'FAVORITE') message.success('已收藏岗位')
      else message.success('已标记为不感兴趣')
    } catch (e: any) {
      message.error(String(e?.response?.data?.detail || e?.message || '操作失败'))
    }
  }

  const columns = useMemo(() => {
    if (recommendMode === 'jobs') {
      return [
        {
          title: '匹配岗位',
          dataIndex: 'title',
          render: (_: any, row: any) => (
            <Button type="link" onClick={(e) => { e.stopPropagation(); void openDetail(row) }}>
              {String(row?.title || '未命名岗位')}
            </Button>
          )
        },
        { title: '公司', dataIndex: 'company_name', render: (v: string) => v || '-' },
        { title: '地点', dataIndex: 'location', render: (v: string) => v || '-' },
        { title: '地点匹配', render: (_: any, row: any) => locationMatchTag(row) },
        { title: '匹配总分', dataIndex: 'overall_score', render: (v: number) => <Tag color={v >= 80 ? 'green' : v >= 65 ? 'blue' : 'orange'}>{Math.round(v)}</Tag> },
        { title: '排序分', dataIndex: 'rank_score', render: (v: number) => <Tag>{Math.round(v || 0)}</Tag> },
        {
          title: '模型精排',
          render: (_: any, row: any) => (
            <Space>
              {row?.bge_rerank_score == null ? <Text type="secondary">-</Text> : <Tag color="purple">BGE {Math.round(Number(row.bge_rerank_score || 0) * 100)}</Tag>}
              {row?.is_low_confidence ? <Tag color="orange">低置信</Tag> : <Tag color="green">可信</Tag>}
            </Space>
          )
        },
        {
          title: '诊断摘要',
          dataIndex: 'ai_rerank_reason',
          render: (v: string, row: any) => {
            const text = String(v || '').trim()
            if (!text) {
              const strengthCount = Number((row?.top_strengths || []).length)
              const gapCount = Number((row?.top_gaps || []).length)
              return <Text type="secondary">优势 {strengthCount} / 短板 {gapCount}，详情生成AI诊断</Text>
            }
            return <Text ellipsis={{ tooltip: text }}>{text}</Text>
          }
        },
        { title: '最终排序分', render: (_: any, row: any) => <Tag color="gold">{Math.round(Number(row?.final_rank_score ?? row?.model_rank_score ?? row?.rank_score ?? 0))}</Tag> },
        { title: '策略', dataIndex: 'strategy', render: (v: string) => <Tag>{strategyLabelMap[v] || '均衡'}</Tag> },
        {
          title: '岗位族',
          render: (_: any, row: any) => (
            <Space>
              <Tag>{row.job_family_label || familyLabel(row.job_family)}</Tag>
              <Tag color="geekblue">硬技能 {Number(row?.job_hard_skill_count || 0)}</Tag>
            </Space>
          )
        },
        {
          title: '证据命中',
          render: (_: any, row: any) => (
            <Space>
              <Tag color="green">优势 {Number((row.top_strengths || []).length)}</Tag>
              <Tag color="orange">短板 {Number((row.top_gaps || []).length)}</Tag>
              {Number((row.skill_transfer_paths || []).length) ? <Tag color="blue">路径 {Number((row.skill_transfer_paths || []).length)}</Tag> : null}
            </Space>
          )
        },
        {
          title: '操作',
          render: (_: any, row: any) => (
            <Space>
              <Button size="small" onClick={(e) => { e.stopPropagation(); void openDetail(row) }}>
                查看详情
              </Button>
              <Button
                size="small"
                type={preferenceOf(row) === 'FAVORITE' ? 'primary' : 'default'}
                icon={preferenceOf(row) === 'FAVORITE' ? <StarFilled /> : <StarOutlined />}
                onClick={(e) => { e.stopPropagation(); void setJobPreference(row, 'FAVORITE') }}
              />
              <Button
                size="small"
                danger={preferenceOf(row) === 'DISMISS'}
                icon={<DislikeOutlined />}
                onClick={(e) => { e.stopPropagation(); void setJobPreference(row, 'DISMISS') }}
              >
                不感兴趣
              </Button>
            </Space>
          )
        }
      ]
    }
    return [
      {
        title: '岗位角色',
        dataIndex: 'title',
        render: (_: any, row: any) => (
          <Button type="link" onClick={(e) => { e.stopPropagation(); void openDetail(row) }}>
            {presentRoleName(row)}
          </Button>
        )
      },
      { title: '匹配总分', dataIndex: 'overall_score', render: (v: number) => <Tag color={v >= 80 ? 'green' : v >= 65 ? 'blue' : 'orange'}>{Math.round(v)}</Tag> },
      { title: '排序分', dataIndex: 'rank_score', render: (v: number) => <Tag>{Math.round(v || 0)}</Tag> },
      { title: '策略', dataIndex: 'strategy', render: (v: string) => <Tag>{strategyLabelMap[v] || '均衡'}</Tag> },
      {
        title: '岗位族/层级',
        render: (_: any, row: any) => (
          <Space>
            <Tag>{row.job_family_label || familyLabel(row.job_family)}</Tag>
            <Tag>{row.level_label_zh || levelLabel(row.level_label)}</Tag>
          </Space>
        )
      },
      { title: '岗位样本数', dataIndex: 'member_count' },
      {
        title: '证据命中',
        render: (_: any, row: any) => (
          <Space>
            <Tag color="green">优势 {Number((row.top_strengths || []).length)}</Tag>
            <Tag color="orange">短板 {Number((row.top_gaps || []).length)}</Tag>
          </Space>
        )
      },
      {
        title: '操作',
        render: (_: any, row: any) => (
          <Button size="small" onClick={(e) => { e.stopPropagation(); void openDetail(row) }}>
            查看详情
          </Button>
        )
      }
    ]
  }, [recommendMode, openDetail, jobPreferences])

  const metrics = useMemo(() => {
    const count = items.length
    const avgScore = count ? Math.round(items.reduce((sum: number, item: any) => sum + Number(item?.overall_score || 0), 0) / count) : 0
    const highFit = items.filter((item: any) => Number(item?.overall_score || 0) >= 75).length
    const highGap = items.filter((item: any) => Number((item?.top_gaps || []).length) >= 4).length
    return { count, avgScore, highFit, highGap }
  }, [items])

  const detailScore = detail?.score || {}
  const detailJob = detail?.job_detail || detail || {}
  const detailJobProfile = detail?.job_profile || {}
  const ai = detailScore?.ai_analysis
  const semantic = detailScore?.semantic_review
  const skillDim = detailScore?.dimension_scores?.skills || {}
  const llmCandidateTop20 = Array.isArray(skillDim?.llm_candidate_top20) ? skillDim.llm_candidate_top20 : []

  return (
    <Space direction="vertical" size={18} style={{ width: '100%' }}>
      {!canWrite ? (
        <Alert type="info" showIcon message="当前账号为只读角色：可查看推荐与岗位详情，但不会执行评分写入与行为日志写入。" />
      ) : null}

      <div className="workbench-hero">
        <div className="workbench-hero-main">
          <Title level={3} className="workbench-title">岗位匹配诊断工作台</Title>
          <div className="workbench-chip-row">
            <Tag color="magenta">对象：{recommendModeLabelMap[recommendMode] || '匹配岗位'}</Tag>
            <Tag color="blue">策略：{strategyLabelMap[strategy] || '均衡'}</Tag>
            {family ? <Tag color="cyan">方向：{familyLabel(family)}</Tag> : <Tag>方向：全部</Tag>}
            {keyword ? <Tag color="geekblue">关键词：{keyword}</Tag> : <Tag>关键词：未设置</Tag>}
            {location ? <Tag color="green">城市：{location}</Tag> : <Tag>城市：未设置</Tag>}
            <Tag color="gold">城市权重：{Math.round(locationWeight * 100)}%</Tag>
            {recommendMode === 'jobs' ? <Tag color={aiRerankEnabled ? 'purple' : 'default'}>BGE精排：{aiRerankEnabled ? '开启' : '关闭'}</Tag> : null}
            {recommendMode === 'jobs' ? <Tag color="magenta">精排候选：Top{aiRerankTopN}</Tag> : null}
            {recommendMode === 'jobs' ? <Tag color="magenta">精排权重：{Math.round(aiRerankWeight * 100)}%</Tag> : null}
            {recommendMode === 'jobs' ? <Tag color={aiRerankDebug ? 'red' : 'default'}>精排日志：{aiRerankDebug ? '开启' : '关闭'}</Tag> : null}
            <Tag color="purple">画像：{profileSourceLabel(profileSource)}</Tag>
          </div>
        </div>
        <Card className="workbench-readiness-card" variant="borderless">
          <div className="workbench-readiness-head">
            <Text className="workbench-readiness-label">推荐质量面板</Text>
            <Tag color="blue">候选 {totalCandidates || items.length}</Tag>
          </div>
          <div className="workbench-readiness-score">{metrics.avgScore}</div>
          <div className="workbench-readiness-meta">平均匹配分</div>
          <div className="workbench-readiness-meta">行为事件：{behaviorUsedEvents}</div>
        </Card>
      </div>

      {recommendError ? <Alert type="error" showIcon message="推荐失败" description={recommendError} /> : null}
      {!recommendError && !items.length && recommendDiagnostics ? (
        <Alert
          type="warning"
          showIcon
          message="本次推荐为空的诊断结果"
          description={
            <Space direction="vertical" size={2}>
              <Text>
                {recommendMode === 'jobs' ? '筛选命中岗位' : '筛选命中角色'}：
                {Number(recommendMode === 'jobs' ? (recommendDiagnostics?.jobs_total || 0) : (recommendDiagnostics?.roles_total || 0))}
              </Text>
              {recommendDiagnostics?.vector_recall_hits !== undefined ? <Text>向量召回命中：{Number(recommendDiagnostics?.vector_recall_hits || 0)}</Text> : null}
              {recommendMode === 'roles' ? (
                <>
                  <Text>无成员岗位角色：{Number(recommendDiagnostics?.roles_without_members || 0)}</Text>
                  <Text>成功评分角色：{Number(recommendDiagnostics?.roles_scored || 0)}</Text>
                  <Text>评分失败角色：{Number(recommendDiagnostics?.roles_score_failed || 0)}</Text>
                </>
              ) : (
                <>
                  <Text>粗排候选池：{Number(recommendDiagnostics?.jobs_recall_pool || 0)}</Text>
                  <Text>精排候选池：{Number(recommendDiagnostics?.jobs_scoring_pool || 0)}</Text>
                  <Text>G-Rank引擎：{String(recommendDiagnostics?.engine || '-')}</Text>
                  <Text>BM25召回：{Number(recommendDiagnostics?.diagnostics?.bm25_hits || 0)} / 语义召回：{Number(recommendDiagnostics?.diagnostics?.semantic_hits || 0)}</Text>
                  <Text>BGE精排：{recommendDiagnostics?.diagnostics?.bge_rerank_enabled ? '开启' : '关闭'}，已评分 {Number(recommendDiagnostics?.diagnostics?.bge_rerank_scored || 0)}</Text>
                  <Text>重复过滤：{Number(recommendDiagnostics?.diagnostics?.duplicate_filtered || 0)}</Text>
                  <Text>AI重排启用：{recommendDiagnostics?.ai_rerank_enabled ? '是' : '否'}</Text>
                  <Text>AI重排命中：{Number(recommendDiagnostics?.ai_rerank_scored_count || 0)}</Text>
                  <Text>传输日志：{recommendDiagnostics?.ai_rerank_debug ? '开启' : '关闭'}</Text>
                </>
              )}
              {recommendDiagnostics?.student_hard_skill_count !== undefined ? (
                <Text>
                  学生硬技能数：{Number(recommendDiagnostics?.student_hard_skill_count || 0)}
                </Text>
              ) : null}
            </Space>
          }
        />
      ) : null}
      {profileSource === 'generated_empty_fallback' ? (
        <Alert
          type="warning"
          showIcon
          message="当前学生画像信息不足，已使用最小兜底画像"
          description="建议先到学生工作台上传简历并执行“从最新简历生成画像”，再回到本页重新推荐。"
          action={<Button size="small" onClick={() => navigate('/student')}>去完善画像</Button>}
        />
      ) : null}

      <Card>
        <Row gutter={[16, 16]}>
          <Col span={5}>
            <Select
              style={{ width: '100%' }}
              placeholder="选择学生"
              value={studentId}
              onChange={setStudentId}
              options={students.map((s, index) => ({ label: presentStudentOption(s, index), value: s.student_id }))}
              showSearch
              filterOption={false}
              onSearch={(value) => { void loadStudents(String(value || '').trim()) }}
            />
          </Col>
          <Col span={3}><Select style={{ width: '100%' }} value={recommendMode} onChange={(value) => setRecommendMode(String(value) === 'roles' ? 'roles' : 'jobs')} options={recommendModeOptions} /></Col>
          <Col span={3}><Select style={{ width: '100%' }} value={family} onChange={setFamily} options={familySelectOptions} /></Col>
          <Col span={3}><Select style={{ width: '100%' }} value={strategy} onChange={setStrategy} options={strategyOptions} /></Col>
          <Col span={4}><Input placeholder="关键词，例如 前端 / 测试 / 运维" value={keyword} onChange={e => setKeyword(e.target.value)} /></Col>
          <Col span={3}><Input placeholder="城市，例如 杭州" value={location} onChange={e => setLocation(e.target.value)} /></Col>
          <Col span={3}><Button type="primary" block onClick={() => void recommend()} loading={loading}>开始推荐</Button></Col>
        </Row>
        <Row style={{ marginTop: 10 }}>
          <Col span={24}>
            <Space direction="vertical" size={4} style={{ width: '100%' }}>
              <Text type="secondary">城市匹配权重（0% 不考虑城市，100% 默认，200% 强城市优先）</Text>
              <Slider
                min={0}
                max={200}
                step={10}
                value={Math.round(locationWeight * 100)}
                onChange={(value) => setLocationWeight(Math.max(0, Math.min(2, Number(value || 0) / 100)))}
                tooltip={{ formatter: (value) => `${value || 0}%` }}
              />
              <Space size={18} wrap style={{ width: '100%' }}>
                <Space>
                  <Text type="secondary">BGE精排</Text>
                  <Switch
                    checked={aiRerankEnabled}
                    onChange={setAiRerankEnabled}
                    disabled={recommendMode !== 'jobs'}
                  />
                </Space>
                <Space direction="vertical" size={0} style={{ minWidth: 220 }}>
                  <Text type="secondary">精排候选数量 TopN：{aiRerankTopN}</Text>
                  <Slider
                    min={5}
                    max={30}
                    step={1}
                    value={aiRerankTopN}
                    onChange={(value) => setAiRerankTopN(Math.max(5, Math.min(30, Number(value || 20))))}
                    disabled={recommendMode !== 'jobs' || !aiRerankEnabled}
                  />
                </Space>
                <Space direction="vertical" size={0} style={{ minWidth: 240 }}>
                  <Text type="secondary">精排权重：{Math.round(aiRerankWeight * 100)}%</Text>
                  <Slider
                    min={0}
                    max={100}
                    step={5}
                    value={Math.round(aiRerankWeight * 100)}
                    onChange={(value) => setAiRerankWeight(Math.max(0, Math.min(1, Number(value || 0) / 100)))}
                    disabled={recommendMode !== 'jobs' || !aiRerankEnabled}
                  />
                </Space>
                <Space>
                  <Text type="secondary">打印精排日志</Text>
                  <Switch
                    checked={aiRerankDebug}
                    onChange={setAiRerankDebug}
                    disabled={recommendMode !== 'jobs' || !aiRerankEnabled}
                  />
                </Space>
              </Space>
            </Space>
          </Col>
        </Row>
      </Card>

      {recommendMode === 'jobs' && aiRerankDebug && aiRerankDebugPayload ? (
        <Card title="AI传输日志（个人信息/岗位信息）">
          <Space direction="vertical" size={8} style={{ width: '100%' }}>
            <Text type="secondary">以下为本次传给 BGE 精排相关链路的数据（学生画像与岗位明细）。</Text>
            <Text>岗位传输条数：{Number(aiRerankDebugPayload?.jobs_sent_count || 0)}</Text>
            <div style={{ maxHeight: 360, overflow: 'auto', background: '#fafafa', border: '1px solid #eee', padding: 10, borderRadius: 6 }}>
              <pre style={{ margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-word', fontSize: 12 }}>
                {JSON.stringify(aiRerankDebugPayload, null, 2)}
              </pre>
            </div>
          </Space>
        </Card>
      ) : null}

      <div className="workbench-grid">
        <Card title={recommendMode === 'jobs' ? '匹配岗位结果' : '匹配角色结果'} className="workbench-card">
          <Table
            rowKey={recommendMode === 'jobs' ? 'job_id' : 'role_id'}
            loading={loading}
            columns={columns as any}
            dataSource={items}
            pagination={{ pageSize: 8 }}
            onRow={(record: any) => ({
              onClick: () => {
                void openDetail(record)
              },
            })}
          />
        </Card>
      </div>

      <Drawer
        open={!!detail}
        width={980}
        title={detail
          ? (detail?.recommendMode === 'jobs'
            ? `${String(detail?.title || '岗位')} · ${String(detail?.company_name || '未知公司')}`
            : presentRoleName(detail))
          : ''}
        onClose={() => setDetail(null)}
      >
        {detail ? (
          <Space direction="vertical" size={16} style={{ width: '100%' }}>
            {detail?.detail_loading ? (
              <Alert type="info" showIcon message="详情加载中..." />
            ) : null}
            <Row gutter={[12, 12]}>
              <Col span={4}><Card size="small"><Title level={5}>总分</Title><div style={{ fontSize: 24, fontWeight: 700 }}>{Math.round(detailScore?.overall_score || 0)}</div></Card></Col>
              <Col span={5}><Card size="small"><Title level={5}>基础要求</Title><Progress percent={Math.round(detailScore?.dimension_scores?.basic?.score || 0)} /></Card></Col>
              <Col span={5}><Card size="small"><Title level={5}>职业技能</Title><Progress percent={Math.round(detailScore?.dimension_scores?.skills?.score || 0)} strokeColor="#1677ff" /></Card></Col>
              <Col span={5}><Card size="small"><Title level={5}>职业素养</Title><Progress percent={Math.round(detailScore?.dimension_scores?.qualities?.score || 0)} strokeColor="#722ed1" /></Card></Col>
              <Col span={5}><Card size="small"><Title level={5}>发展潜力</Title><Progress percent={Math.round(detailScore?.dimension_scores?.potential?.score || 0)} strokeColor="#52c41a" /></Card></Col>
            </Row>

            {detail?.recommendMode === 'jobs' ? (
              <Card size="small" title="岗位详细信息">
                <Space direction="vertical" size={12} style={{ width: '100%' }}>
                  <Space>
                    <Button
                      type={preferenceOf(detail) === 'FAVORITE' ? 'primary' : 'default'}
                      icon={preferenceOf(detail) === 'FAVORITE' ? <StarFilled /> : <StarOutlined />}
                      onClick={() => void setJobPreference(detail, 'FAVORITE')}
                    >
                      {preferenceOf(detail) === 'FAVORITE' ? '已收藏' : '收藏岗位'}
                    </Button>
                    <Button
                      danger={preferenceOf(detail) === 'DISMISS'}
                      icon={<DislikeOutlined />}
                      onClick={() => void setJobPreference(detail, 'DISMISS')}
                    >
                      {preferenceOf(detail) === 'DISMISS' ? '已标记不感兴趣' : '不感兴趣'}
                    </Button>
                  </Space>
                  <Descriptions size="small" column={2} bordered>
                    <Descriptions.Item label="岗位ID">{String(detailJob?.job_id || detail?.job_id || '-')}</Descriptions.Item>
                    <Descriptions.Item label="公司">{String(detailJob?.company_name || detail?.company_name || '-')}</Descriptions.Item>
                    <Descriptions.Item label="地点">{String(detailJob?.location || detail?.location || '-')}</Descriptions.Item>
                    <Descriptions.Item label="薪资">{salaryText(detailJob)}</Descriptions.Item>
                    <Descriptions.Item label="岗位族">{String(detail?.job_family_label || familyLabel(detail?.job_family) || '-')}</Descriptions.Item>
                    <Descriptions.Item label="方向关系">{String(skillDim?.relation || detail?.match_relation || '-')}</Descriptions.Item>
                    <Descriptions.Item label="BGE精排分">{detail?.bge_rerank_score == null ? '-' : Math.round(Number(detail.bge_rerank_score || 0) * 100)}</Descriptions.Item>
                    <Descriptions.Item label="最终排序分">{Math.round(Number(detail?.final_rank_score ?? detail?.model_rank_score ?? detail?.rank_score ?? 0))}</Descriptions.Item>
                    <Descriptions.Item label="置信状态">{detail?.is_low_confidence ? '低置信候选' : '精准匹配'}</Descriptions.Item>
                    <Descriptions.Item label="关键词命中">{(detail?.query_anchor_hits || []).join('、') || '-'}</Descriptions.Item>
                    <Descriptions.Item label="证据质量">{(detail?.evidence_quality?.warnings || []).join('、') || '证据充足'}</Descriptions.Item>
                    <Descriptions.Item label="岗位证据数">{Number(detail?.evidence_quality?.job_signal_count || 0)}</Descriptions.Item>
                  </Descriptions>
                  {String(detail?.ai_rerank_reason || '').trim() ? (
                    <Alert
                      type="info"
                      showIcon
                      message={`AI重排理由：${String(detail.ai_rerank_reason || '')}`}
                    />
                  ) : null}

                  {(detailJobProfile?.hard_skills || []).length ? (
                    <div>
                      <Text strong>岗位硬技能：</Text>
                      <div style={{ marginTop: 8 }}>
                        <Space size={[0, 6]} wrap>
                          {(detailJobProfile?.hard_skills || []).slice(0, 16).map((it: any, idx: number) => (
                            <Tag key={`${it?.mention || it?.name || idx}`}>{String(it?.mention || it?.name || '-')}</Tag>
                          ))}
                        </Space>
                      </div>
                    </div>
                  ) : null}

                  {(detailJob?.description || detail?.description) ? (
                    <div>
                      <Text strong>岗位描述：</Text>
                      <div style={{ marginTop: 8, whiteSpace: 'pre-wrap', lineHeight: 1.6 }}>
                        {String(detailJob?.description || detail?.description || '').slice(0, 2200)}
                      </div>
                    </div>
                  ) : null}
                </Space>
              </Card>
            ) : null}

            <Card size="small" title="优势 / 待提升">
              <Space direction="vertical" size={12} style={{ width: '100%' }}>
                <div>
                  <Text strong>优势：</Text>
                  <div style={{ marginTop: 8 }}>
                    <Space size={[0, 8]} wrap>
                      {(detail.top_strengths || []).map((value: string) => <Tag color="green" key={value}>{value}</Tag>)}
                    </Space>
                  </div>
                </div>
                <div>
                  <Text strong>待提升：</Text>
                  <div style={{ marginTop: 8 }}>
                    <Space size={[0, 8]} wrap>
                      {(detail.top_gaps || []).map((value: string) => <Tag color="orange" key={value}>{value}</Tag>)}
                    </Space>
                  </div>
                </div>
              </Space>
            </Card>

            {detail?.recommendMode === 'jobs' ? (
              <Card size="small" title="技能迁移与熟练度">
                <Space direction="vertical" size={14} style={{ width: '100%' }}>
                  <div>
                    <Text strong>熟练度证据：</Text>
                    {!Number((detail?.proficiency_evidence || []).length) ? (
                      <div style={{ marginTop: 8 }}><Text type="secondary">暂无熟练度证据。</Text></div>
                    ) : (
                      <List
                        size="small"
                        dataSource={(detail?.proficiency_evidence || []).slice(0, 6)}
                        renderItem={(item: any) => (
                          <List.Item>
                            <Space direction="vertical" size={2} style={{ width: '100%' }}>
                              <Space size={[6, 6]} wrap>
                                <Tag color={item?.relation === 'exact' ? 'green' : 'blue'}>{item?.relation === 'exact' ? '直接命中' : '可迁移'}</Tag>
                                <Text strong>{String(item?.student_skill || '-')} → {String(item?.name || '-')}</Text>
                                <Tag>学生 {String(item?.student_proficiency?.label || '-')}</Tag>
                                <Tag>岗位 {String(item?.required_proficiency?.label || '-')}</Tag>
                              </Space>
                              <Text type="secondary">{String(item?.student_proficiency?.evidence || item?.reason || '')}</Text>
                            </Space>
                          </List.Item>
                        )}
                      />
                    )}
                  </div>

                  <div>
                    <Text strong>能力缺口路径：</Text>
                    {!Number((detail?.skill_transfer_paths || []).length) ? (
                      <div style={{ marginTop: 8 }}><Text type="secondary">暂无明显技能缺口路径。</Text></div>
                    ) : (
                      <List
                        size="small"
                        dataSource={(detail?.skill_transfer_paths || []).slice(0, 5)}
                        renderItem={(item: any) => (
                          <List.Item>
                            <Space direction="vertical" size={4} style={{ width: '100%' }}>
                              <Space><Tag color="orange">{String(item?.target_skill || '-')}</Tag><Text type="secondary">{String(item?.cluster || '')}</Text></Space>
                              <Space size={[4, 4]} wrap>
                                {(item?.steps || []).map((step: string, idx: number) => <Tag key={`${step}-${idx}`}>{idx + 1}. {step}</Tag>)}
                              </Space>
                            </Space>
                          </List.Item>
                        )}
                      />
                    )}
                  </div>

                  <div>
                    <Text strong>反事实提升建议：</Text>
                    {!Number((detail?.counterfactual_actions || []).length) ? (
                      <div style={{ marginTop: 8 }}><Text type="secondary">暂无可量化提升建议。</Text></div>
                    ) : (
                      <List
                        size="small"
                        dataSource={(detail?.counterfactual_actions || []).slice(0, 6)}
                        renderItem={(item: any) => (
                          <List.Item>
                            <Space direction="vertical" size={2} style={{ width: '100%' }}>
                              <Text>{String(item?.action || '')}</Text>
                              <Space>
                                <Tag color="blue">预计 +{Number(item?.estimated_gain || 0).toFixed(1)}</Tag>
                                <Tag color="gold">可达 {Number(item?.estimated_score_after || 0).toFixed(1)}</Tag>
                              </Space>
                            </Space>
                          </List.Item>
                        )}
                      />
                    )}
                  </div>
                </Space>
              </Card>
            ) : null}

            <Card size="small" title="候选技能检索（Top20）">
              {!llmCandidateTop20.length ? (
                <Text type="secondary">暂无检索候选。</Text>
              ) : (
                <List
                  size="small"
                  dataSource={llmCandidateTop20.slice(0, 20)}
                  renderItem={(item: any) => (
                    <List.Item>
                      <Space direction="vertical" size={2} style={{ width: '100%' }}>
                        <Space size={[6, 6]} wrap>
                          <Tag color={item?.importance === 'must' ? 'red' : item?.importance === 'must_low' ? 'orange' : 'default'}>
                            {item?.importance || 'plus'}
                          </Tag>
                          <Text strong>{String(item?.name || item?.skill_id || '未知技能')}</Text>
                          <Tag>retrieval {Number(item?.retrieval_score || 0).toFixed(2)}</Tag>
                        </Space>
                        <Space size={[4, 4]} wrap>
                          {(item?.reasons || []).slice(0, 3).map((reason: string) => <Tag key={reason}>{reason}</Tag>)}
                        </Space>
                      </Space>
                    </List.Item>
                  )}
                />
              )}
            </Card>

            <Card size="small" title="语义复核">
              {!semantic ? (
                <Text type="secondary">未返回语义复核结果。</Text>
              ) : (
                <Space direction="vertical" size={12} style={{ width: '100%' }}>
                  <Space size={[8, 8]} wrap>
                    <Tag color={relevanceTagColor(semantic?.relevance)}>相关性 {String(semantic?.relevance || 'unknown')}</Tag>
                    <Tag>basic {Math.round(Number(semantic?.basic || 0))}</Tag>
                    <Tag>skills {Math.round(Number(semantic?.skills || 0))}</Tag>
                    <Tag>qualities {Math.round(Number(semantic?.qualities || 0))}</Tag>
                    <Tag>potential {Math.round(Number(semantic?.potential || 0))}</Tag>
                  </Space>
                  <div>
                    <Text strong>语义命中技能：</Text>
                    <div style={{ marginTop: 8 }}>
                      <Space size={[0, 6]} wrap>
                        {(semantic?.matched_skills || []).map((value: string) => <Tag color="green" key={value}>{value}</Tag>)}
                      </Space>
                    </div>
                  </div>
                  <div>
                    <Text strong>语义缺口技能：</Text>
                    <div style={{ marginTop: 8 }}>
                      <Space size={[0, 6]} wrap>
                        {(semantic?.gap_skills || []).map((value: string) => <Tag color="orange" key={value}>{value}</Tag>)}
                      </Space>
                    </div>
                  </div>
                  {semantic?.summary ? <Alert type="info" showIcon message={String(semantic.summary)} /> : null}
                </Space>
              )}
            </Card>

            {detail?.ai_analysis_loading ? (
              <Alert type="info" showIcon message="AI诊断生成中..." description="基础评分已完成，正在单独请求大模型诊断；大模型不可用时会自动展示规则兜底诊断。" />
            ) : null}

            {detail?.ai_analysis_error ? (
              <Alert type="warning" showIcon message="AI诊断暂未生成" description={detail.ai_analysis_error} />
            ) : null}

            {ai ? (
              <Card size="small" title="AI诊断说明">
                <Space direction="vertical" size={10} style={{ width: '100%' }}>
                  <Space wrap>
                    <Tag color={ai.llm_used ? 'purple' : 'gold'}>{ai.llm_used ? '大模型诊断' : '规则兜底'}</Tag>
                    {ai.source ? <Tag>{String(ai.source)}</Tag> : null}
                    {!ai.llm_used && ai.fallback_reason ? <Tag color="orange">{String(ai.fallback_reason)}</Tag> : null}
                  </Space>
                  <div><Text strong>总结：</Text><Text>{ai.summary}</Text></div>
                  {!!(ai.strengths || []).length && (
                    <div>
                      <Text strong>匹配优势：</Text>
                      <ul style={{ marginTop: 8, paddingLeft: 20 }}>
                        {(ai.strengths || []).slice(0, 4).map((value: string) => <li key={value}>{value}</li>)}
                      </ul>
                    </div>
                  )}
                  {!!(ai.gaps || []).length && (
                    <div>
                      <Text strong>能力差距：</Text>
                      <ul style={{ marginTop: 8, paddingLeft: 20 }}>
                        {(ai.gaps || []).slice(0, 4).map((value: string) => <li key={value}>{value}</li>)}
                      </ul>
                    </div>
                  )}
                  {!!(ai.next_actions || []).length && (
                    <div>
                      <Text strong>下一步行动：</Text>
                      <ol style={{ marginTop: 8, paddingLeft: 20 }}>
                        {(ai.next_actions || []).slice(0, 6).map((value: string) => <li key={value}>{value}</li>)}
                      </ol>
                    </div>
                  )}
                  {ai.risk_hint ? <Alert type={ai.llm_used ? 'info' : 'warning'} showIcon message={String(ai.risk_hint)} /> : null}
                </Space>
              </Card>
            ) : null}

            <Card size="small" title="下一步">
              <Text>该页面用于解释推荐原因，正式报告请在报告中心生成。</Text>
              <div style={{ marginTop: 12 }}>
                <Button
                  type="primary"
                  onClick={() => {
                    if (detail?.recommendMode === 'roles' && detail?.role_id) {
                      navigate(`/report?student_id=${studentId}&role_id=${detail.role_id}`)
                      return
                    }
                    const targetJobId = String(detail?.job_id || detail?.job_detail?.job_id || '').trim()
                    if (targetJobId) {
                      navigate(`/report?student_id=${studentId}&target_job_id=${encodeURIComponent(targetJobId)}&auto_generate_job=1`)
                      return
                    }
                    navigate(`/report?student_id=${studentId}`)
                  }}
                  disabled={!canWrite}
                >
                  {detail?.recommendMode === 'roles' ? '基于该角色生成报告' : '基于该岗位继续生成报告'}
                </Button>
              </div>
            </Card>
          </Space>
        ) : null}
      </Drawer>
    </Space>
  )
}
