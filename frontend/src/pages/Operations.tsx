import React, { useEffect, useMemo, useState } from 'react'
import {
  App,
  Button,
  Card,
  Col,
  Descriptions,
  Drawer,
  Empty,
  Form,
  Input,
  InputNumber,
  Modal,
  Row,
  Select,
  Space,
  Statistic,
  Switch,
  Table,
  Tabs,
  Tag,
  Typography,
  Upload
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import {
  CloudUploadOutlined,
  DatabaseOutlined,
  SettingOutlined,
  UserSwitchOutlined
} from '@ant-design/icons'
import { api } from '../api/client'

const { Paragraph, Text, Title } = Typography

type Summary = {
  counts?: Record<string, number>
  tasks?: Record<string, number>
  llm?: Record<string, any>
}

type JobItem = {
  job_id: string
  title: string
  location?: string
  company_name?: string
  industry?: string
  company_intro?: string
  job_code?: string
  source_url?: string
  salary_min?: number
  salary_max?: number
  salary_period?: string
  updated_date?: string
  description?: string
}

type StudentItem = {
  student_id: string
  name?: string
}

type UserItem = {
  user_id: string
  username: string
  display_name?: string
  role: 'admin' | 'operator' | 'viewer'
  is_active: boolean | number
  created_at?: string
}

type PreviewData = {
  filename?: string
  sheet_names?: string[]
  columns?: string[]
  row_count?: number
  sample_rows?: Record<string, any>[]
  mapped_fields?: { source: string; target: string }[]
}

type PipelineResult = {
  source_path?: string
  sheet_name?: string | number | null
  task_ids?: string[]
  preview?: {
    row_count?: number
    columns?: string[]
    mapped_fields?: { source: string; target: string }[]
  }
}

type ProviderPreset = {
  provider: string
  label: string
}

type EvalGuide = {
  skill_match_accuracy?: { target?: number }
  profile_accuracy?: { target?: number }
}

type SampleRow = Record<string, any>

const SAMPLE_FIELD_LABELS: Record<string, string> = {
  student_id: '学生ID',
  student_name: '学生姓名',
  job_id: '岗位ID',
  job_title: '岗位名称',
  entity_id: '实体ID',
  entity_type: '实体类型',
  field_name: '字段名',
  true_match: '人工标注匹配',
  pred_match: '系统预测匹配',
  true_value: '人工标注值',
  pred_value: '系统预测值',
  confidence: '置信度',
  reason: '说明',
  source_text: '原文片段',
  bucket: '分桶',
  error_type: '错误类型'
}

function presentFieldLabel(key: string): string {
  const zh = SAMPLE_FIELD_LABELS[key]
  return zh ? `${zh} (${key})` : key
}

function formatPercent(value: unknown): string {
  const num = Number(value)
  return Number.isFinite(num) ? `${(num * 100).toFixed(2)}%` : '-'
}

function salaryText(item: JobItem) {
  const a = item.salary_min
  const b = item.salary_max
  if (!a && !b) return '面议'
  return `${a || '-'} - ${b || '-'} / ${item.salary_period || 'month'}`
}

function roleTag(role: string) {
  if (role === 'admin') return <Tag color="red">系统管理员</Tag>
  if (role === 'operator') return <Tag color="blue">就业老师</Tag>
  return <Tag>展示账号</Tag>
}

function normalizeProfileTags(items: any[] | undefined, keys: string[]) {
  const out: string[] = []
  const seen = new Set<string>()
  for (const item of items || []) {
    let raw = ''
    if (typeof item === 'string') {
      raw = item
    } else {
      for (const key of keys) {
        const v = item?.[key]
        if (v !== undefined && v !== null && String(v).trim()) {
          raw = String(v)
          break
        }
      }
    }
    const name = raw.trim()
    if (!name) continue
    const dedupeKey = name.toLowerCase()
    if (seen.has(dedupeKey)) continue
    seen.add(dedupeKey)
    out.push(name)
  }
  return out
}

export default function Operations() {
  const { message } = App.useApp()

  const [summary, setSummary] = useState<Summary>({})
  const [jobs, setJobs] = useState<JobItem[]>([])
  const [jobTotal, setJobTotal] = useState(0)
  const [jobPage, setJobPage] = useState(1)
  const [jobPageSize, setJobPageSize] = useState(100)
  const [jobQuery, setJobQuery] = useState('')
  const [students, setStudents] = useState<StudentItem[]>([])
  const [jobIdOptions, setJobIdOptions] = useState<Array<{ label: string; value: string }>>([])
  const [users, setUsers] = useState<UserItem[]>([])
  const [providers, setProviders] = useState<ProviderPreset[]>([])
  const [llmLogs, setLlmLogs] = useState<any[]>([])
  const [appLogs, setAppLogs] = useState<any[]>([])
  const [evalGuide, setEvalGuide] = useState<EvalGuide | null>(null)
  const [skillLabelExport, setSkillLabelExport] = useState<any | null>(null)
  const [profileLabelExport, setProfileLabelExport] = useState<any | null>(null)
  const [skillEvalResult, setSkillEvalResult] = useState<any | null>(null)
  const [profileEvalResult, setProfileEvalResult] = useState<any | null>(null)
  const [skillEvalFile, setSkillEvalFile] = useState<File | null>(null)
  const [profileEvalFile, setProfileEvalFile] = useState<File | null>(null)

  const [preview, setPreview] = useState<PreviewData | null>(null)
  const [selectedFile, setSelectedFile] = useState<File | null>(null)

  const [pipelineResult, setPipelineResult] = useState<PipelineResult | null>(null)
  const [resumeBatchResult, setResumeBatchResult] = useState<any | null>(null)
  const [debugChatInput, setDebugChatInput] = useState('1+1=几？')
  const [debugChatResult, setDebugChatResult] = useState<any | null>(null)

  const [jobDrawerOpen, setJobDrawerOpen] = useState(false)
  const [userDrawerOpen, setUserDrawerOpen] = useState(false)
  const [jobProfileDrawerOpen, setJobProfileDrawerOpen] = useState(false)
  const [editingJob, setEditingJob] = useState<JobItem | null>(null)
  const [editingUser, setEditingUser] = useState<UserItem | null>(null)
  const [activeJobProfile, setActiveJobProfile] = useState<any>(null)
  const [jobProfileLoading, setJobProfileLoading] = useState(false)
  const [jobEditorLoading, setJobEditorLoading] = useState(false)

  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [pipelineLoading, setPipelineLoading] = useState(false)
  const [quickLlmLoading, setQuickLlmLoading] = useState(false)
  const [evalLoading, setEvalLoading] = useState(false)

  const [jobForm] = Form.useForm()
  const [userForm] = Form.useForm()
  const [llmForm] = Form.useForm()
  const [importForm] = Form.useForm()
  const [evalSkillForm] = Form.useForm()
  const [evalProfileForm] = Form.useForm()
  const selectedProvider = Form.useWatch('provider', llmForm)

  const closeJobDrawer = () => {
    setJobDrawerOpen(false)
  }

  const closeUserDrawer = () => {
    setUserDrawerOpen(false)
  }

  const closeJobProfileDrawer = () => {
    setJobProfileDrawerOpen(false)
    setJobProfileLoading(false)
    setActiveJobProfile(null)
  }

  const loadSummary = async () => {
    const [summaryRes, providerRes, llmRes, llmLogRes, appLogRes, evalGuideRes] = await Promise.all([
      api.get('/admin/summary'),
      api.get('/admin/llm/providers'),
      api.get('/admin/llm/config'),
      api.get('/admin/logs/llm/model_calls', { params: { limit: 20 } }),
      api.get('/admin/logs/app', { params: { limit: 12 } }),
      api.get('/admin/eval/guide')
    ])

    setSummary(summaryRes.data || {})
    setProviders(providerRes.data?.items || [])
    setLlmLogs(llmLogRes.data?.items || [])
    setAppLogs(appLogRes.data?.items || [])
    setEvalGuide(evalGuideRes.data || null)

    llmForm.setFieldsValue({
      provider: llmRes.data?.provider || 'zhipu',
      enabled: !!llmRes.data?.enabled,
      base_url: llmRes.data?.base_url || '',
      model: llmRes.data?.model || '',
      api_key: '',
      timeout_seconds: llmRes.data?.timeout_seconds || 60,
      temperature: llmRes.data?.temperature ?? 0.2
    })
  }

  const loadJobOptions = async (keyword: string = '') => {
    const normalizedKeyword = String(keyword || '').trim()
    let items: any[] = []
    if (!normalizedKeyword) {
      const res = await api.get('/admin/jobs', {
        params: { limit: 100, offset: 0 }
      })
      items = Array.isArray(res.data?.items) ? res.data.items : []
    } else {
      const pageSize = 500
      let offset = 0
      let pages = 0
      while (true) {
        const res = await api.get('/admin/jobs', {
          params: { limit: pageSize, offset, q: normalizedKeyword }
        })
        const part = Array.isArray(res.data?.items) ? res.data.items : []
        items.push(...part)
        pages += 1
        if (part.length < pageSize || pages >= 100) {
          break
        }
        offset += pageSize
      }
    }
    const options = items
      .map((item: any) => ({
        label: `${String(item?.job_id || '')} | ${String(item?.title || '')}`,
        value: String(item?.job_id || '')
      }))
      .filter((item: { label: string; value: string }) => !!item.value)
    setJobIdOptions(options)
  }

  const loadJobs = async (params?: { page?: number; pageSize?: number; q?: string }) => {
    const page = Number(params?.page || jobPage)
    const pageSize = Number(params?.pageSize || jobPageSize)
    const q = String(params?.q ?? jobQuery)
    const offset = (page - 1) * pageSize
    const res = await api.get('/admin/jobs', {
      params: { limit: pageSize, offset, q: q || undefined }
    })
    setJobs(res.data?.items || [])
    setJobTotal(Number(res.data?.total || 0))
    setJobPage(page)
    setJobPageSize(pageSize)
    setJobQuery(q)
  }

  const loadUsers = async () => {
    const res = await api.get('/admin/users', { params: { limit: 200 } })
    setUsers((res.data?.items || []).map((item: any) => ({ ...item, is_active: !!item?.is_active })))
  }

  const loadStudents = async (keyword: string = '') => {
    const normalizedKeyword = String(keyword || '').trim()
    let items: any[] = []
    if (!normalizedKeyword) {
      const res = await api.get('/students', {
        params: { limit: 100, offset: 0 }
      })
      items = Array.isArray(res.data?.items) ? res.data.items : []
    } else {
      const pageSize = 500
      let offset = 0
      let pages = 0
      while (true) {
        const res = await api.get('/students', {
          params: { limit: pageSize, offset, q: normalizedKeyword }
        })
        const part = Array.isArray(res.data?.items) ? res.data.items : []
        items.push(...part)
        pages += 1
        if (part.length < pageSize || pages >= 100) {
          break
        }
        offset += pageSize
      }
    }
    setStudents(items.map((item: any) => ({
      student_id: String(item?.student_id || ''),
      name: String(item?.name || '')
    })).filter((item: StudentItem) => !!item.student_id))
  }

  const loadAll = async () => {
    await Promise.all([loadSummary(), loadJobs({ page: 1, pageSize: jobPageSize, q: jobQuery }), loadUsers(), loadStudents(), loadJobOptions()])
  }

  useEffect(() => {
    loadAll().catch(() => message.error('系统管理页加载失败'))
  }, [])

  const statItems = useMemo(() => {
    const counts = summary.counts || {}
    return [
      { title: '岗位总数', value: counts.jobs || 0 },
      { title: '岗位画像', value: counts.job_profiles || 0 },
      { title: '学生画像', value: counts.student_profiles || 0 },
      { title: '报告数量', value: counts.reports || 0 }
    ]
  }, [summary])

  const studentIdOptions = useMemo(
    () => students.map((item) => ({ label: `${item.student_id} | ${item.name || '-'}`, value: item.student_id })),
    [students]
  )

  const skillSampleRows: SampleRow[] = Array.isArray(skillLabelExport?.sample_rows) ? skillLabelExport.sample_rows : []
  const profileSampleRows: SampleRow[] = Array.isArray(profileLabelExport?.sample_rows) ? profileLabelExport.sample_rows : []

  const buildSampleColumns = (rows: SampleRow[]): ColumnsType<SampleRow> => {
    const first = rows[0] || {}
    return Object.keys(first).map((key) => ({
      title: presentFieldLabel(key),
      dataIndex: key,
      key,
      width: 190,
      ellipsis: true
    }))
  }

  const skillSampleColumns = useMemo(() => buildSampleColumns(skillSampleRows), [skillSampleRows])
  const profileSampleColumns = useMemo(() => buildSampleColumns(profileSampleRows), [profileSampleRows])

  const jobColumns: ColumnsType<JobItem> = [
    { title: '岗位ID', dataIndex: 'job_id', width: 140, fixed: 'left' },
    { title: '岗位名称', dataIndex: 'title', width: 220, fixed: 'left' },
    { title: '工作地点', dataIndex: 'location', width: 140 },
    { title: '公司名称', dataIndex: 'company_name', width: 220 },
    { title: '所属行业', dataIndex: 'industry', width: 180 },
    { title: '薪资范围', width: 180, render: (_, record) => salaryText(record) },
    { title: '更新日期', dataIndex: 'updated_date', width: 120 },
    {
      title: '操作',
      width: 220,
      fixed: 'right',
      render: (_, record) => (
        <Space>
          <Button size="small" onClick={() => void viewJobProfile(record.job_id)}>画像</Button>
          <Button size="small" onClick={() => void openJobEditor(record)}>编辑</Button>
          <Button size="small" danger onClick={() => removeJob(record.job_id)}>删除</Button>
        </Space>
      )
    }
  ]

  const userColumns: ColumnsType<UserItem> = [
    { title: '账号', dataIndex: 'username', width: 160 },
    { title: '显示名称', dataIndex: 'display_name', width: 160 },
    { title: '权限', width: 140, render: (_, record) => roleTag(record.role) },
    { title: '状态', width: 100, render: (_, record) => record.is_active ? <Tag color="green">启用</Tag> : <Tag>停用</Tag> },
    { title: '创建时间', dataIndex: 'created_at', width: 180 },
    { title: '操作', width: 120, render: (_, record) => <Button size="small" onClick={() => openUserEditor(record)}>编辑</Button> }
  ]

  const openJobEditor = async (record?: JobItem) => {
    closeUserDrawer()
    closeJobProfileDrawer()
    setEditingJob(record || null)
    setJobEditorLoading(true)
    const base: Record<string, any> = {
      salary_period: 'month',
      auto_generate_profile: !record,
      profile_hard_skills: [],
      profile_soft_skills: [],
      profile_certificates: [],
      profile_tags: []
    }
    if (record) {
      Object.assign(base, record, { auto_generate_profile: false })
    }
    try {
      if (record?.job_id) {
        const res = await api.get(`/jobs/${record.job_id}`)
        const job = res.data?.job || {}
        const profile = res.data?.profile?.profile || {}
        const hardSkills = Array.isArray(profile?.hard_skills)
          ? profile.hard_skills.map((x: any) => String(x?.mention || x?.name || x?.skill_id || '').trim()).filter(Boolean)
          : []
        const softSkills = Array.isArray(profile?.soft_skills)
          ? profile.soft_skills.map((x: any) => String(x?.name || x?.mention || x?.soft_skill_id || '').trim()).filter(Boolean)
          : []
        const certs = Array.isArray(profile?.certificates)
          ? profile.certificates.map((x: any) => String(x?.name || x?.certificate_id || '').trim()).filter(Boolean)
          : []
        const tags = Array.isArray(profile?.tags)
          ? profile.tags.map((x: any) => String(x || '').trim()).filter(Boolean)
          : []
        Object.assign(base, {
          ...job,
          profile_job_family: profile?.job_family || '',
          profile_hard_skills: hardSkills,
          profile_soft_skills: softSkills,
          profile_certificates: certs,
          profile_tags: tags,
          profile_education: profile?.basic_requirements?.education || '',
          profile_experience_years_min: profile?.basic_requirements?.experience_years_min,
        })
      }
      jobForm.setFieldsValue(base)
    } finally {
      setJobEditorLoading(false)
    }
    setJobDrawerOpen(true)
  }

  const openUserEditor = (record?: UserItem) => {
    closeJobDrawer()
    closeJobProfileDrawer()
    setEditingUser(record || null)
    userForm.setFieldsValue(record || { role: 'viewer', is_active: true })
    setUserDrawerOpen(true)
  }

  const viewJobProfile = async (jobId: string) => {
    const id = String(jobId || '').trim()
    if (!id) return
    closeJobDrawer()
    closeUserDrawer()
    setJobProfileDrawerOpen(true)
    setJobProfileLoading(true)
    setActiveJobProfile({ job: { job_id: id } })
    try {
      const res = await api.get(`/jobs/${id}`)
      setActiveJobProfile(res.data || { job: { job_id: id } })
    } catch (e: any) {
      setActiveJobProfile({
        job: { job_id: id },
        error: String(e?.response?.data?.detail || e?.message || '岗位画像加载失败')
      })
    } finally {
      setJobProfileLoading(false)
    }
  }

  const saveJob = async () => {
    const values = await jobForm.validateFields()
    const toNames = (arr: unknown): string[] =>
      (Array.isArray(arr) ? arr : [])
        .map((x) => String(x || '').trim())
        .filter(Boolean)

    const payload: Record<string, any> = {
      job_id: editingJob?.job_id,
      title: values.title,
      location: values.location,
      company_name: values.company_name,
      industry: values.industry,
      company_intro: values.company_intro,
      job_code: values.job_code,
      source_url: values.source_url,
      salary_min: values.salary_min,
      salary_max: values.salary_max,
      salary_period: values.salary_period,
      description: values.description,
      auto_generate_profile: !!values.auto_generate_profile,
    }

    const manualProfile = {
      job_family: String(values.profile_job_family || '').trim() || null,
      hard_skills: toNames(values.profile_hard_skills),
      soft_skills: toNames(values.profile_soft_skills),
      certificates: toNames(values.profile_certificates),
      tags: toNames(values.profile_tags),
      basic_requirements: {
        education: String(values.profile_education || '').trim() || null,
        experience_years_min:
          values.profile_experience_years_min === undefined || values.profile_experience_years_min === null || values.profile_experience_years_min === ''
            ? null
            : Number(values.profile_experience_years_min),
      }
    }

    if (
      editingJob
      || manualProfile.job_family
      || manualProfile.hard_skills.length
      || manualProfile.soft_skills.length
      || manualProfile.certificates.length
      || manualProfile.tags.length
      || manualProfile.basic_requirements.education
      || manualProfile.basic_requirements.experience_years_min !== null
    ) {
      payload.profile = manualProfile
    }

    setSaving(true)
    try {
      await api.post('/admin/jobs/upsert', payload)
      message.success(editingJob ? '岗位已更新' : '岗位已新增')
      closeJobDrawer()
      await loadJobs()
    } finally {
      setSaving(false)
    }
  }

  const saveUser = async () => {
    const values = await userForm.validateFields()
    setSaving(true)
    try {
      await api.post('/admin/users/upsert', { ...editingUser, ...values })
      message.success(editingUser ? '账号已更新' : '账号已新增')
      closeUserDrawer()
      await loadUsers()
    } finally {
      setSaving(false)
    }
  }

  const removeJob = async (jobId: string) => {
    Modal.confirm({
      title: '确认删除该岗位吗？',
      content: '删除后将同步清理该岗位相关画像和关联缓存。',
      okText: '确认删除',
      cancelText: '取消',
      onOk: async () => {
        await api.delete(`/admin/jobs/${jobId}`)
        message.success('岗位已删除')
        await loadJobs()
      }
    })
  }

  const previewFile = async () => {
    if (!selectedFile) {
      message.warning('请先选择 Excel 文件')
      return
    }
    const data = new FormData()
    data.append('file', selectedFile)
    data.append('sheet_name', String(importForm.getFieldValue('sheet_name') || 0))
    const res = await api.post('/admin/import/excel_preview', data, {
      headers: { 'Content-Type': 'multipart/form-data' }
    })
    setPreview(res.data || null)
    message.success('导入预览完成')
  }

  const importFile = async () => {
    if (!selectedFile) {
      message.warning('请先选择 Excel 文件')
      return
    }
    const data = new FormData()
    data.append('file', selectedFile)
    data.append('sheet_name', String(importForm.getFieldValue('sheet_name') || 0))
    const res = await api.post('/jobs/ingest_file', data, {
      headers: { 'Content-Type': 'multipart/form-data' }
    })
    message.success(`导入任务已创建：${res.data?.task_id || ''}`)
    await loadSummary()
  }

  const saveLlm = async () => {
    const values = await llmForm.validateFields()
    await api.post('/admin/llm/config', values)
    message.success('模型配置已保存')
    await loadSummary()
  }

  const applyZhipuPreset = () => {
    llmForm.setFieldsValue({
      provider: 'zhipu',
      enabled: true,
      base_url: 'https://open.bigmodel.cn/api/paas/v4',
      model: 'glm-4.5-air',
      timeout_seconds: 60,
      temperature: 0.2
    })
    message.success('已填入智谱 GLM-4.5-Air 推荐参数')
  }

  const testLlm = async () => {
    setTesting(true)
    try {
      const res = await api.post('/admin/llm/test')
      if (res.data?.ok) {
        message.success('外部模型连通成功')
      } else {
        message.error(res.data?.message || '外部模型连通失败')
      }
      await loadSummary()
    } finally {
      setTesting(false)
    }
  }

  const runQuickLlmSmokeTest = async () => {
    setQuickLlmLoading(true)
    try {
      const res = await api.post('/admin/llm/chat_debug', {
        message: '1+1=几？请只回答数字。',
        json_mode: false
      })
      setDebugChatResult(res.data || null)
      if (res.data?.ok) {
        const answer = typeof res.data?.result === 'string' ? res.data.result : JSON.stringify(res.data?.result || {})
        message.success(`模型冒烟测试完成：${String(answer).slice(0, 40)}`)
      } else {
        message.warning(res.data?.message || '模型冒烟测试失败')
      }
      await loadSummary()
    } finally {
      setQuickLlmLoading(false)
    }
  }

  const runCompetitionXlsPipeline = async () => {
    setPipelineLoading(true)
    try {
      const res = await api.post('/admin/pipeline/import_competition_xls', {
        clear_existing: false,
        build_kb: true,
        build_graph: true,
        build_vectors: true
      })
      setPipelineResult(res.data || null)
      message.success(`已创建任务链：${(res.data?.task_ids || []).length} 个任务`)
      await loadSummary()
    } finally {
      setPipelineLoading(false)
    }
  }

  const runResumeBatchAiStrict = async () => {
    setPipelineLoading(true)
    try {
      const res = await api.post('/students/batch/import_competition_resumes', {
        overwrite_existing: true,
        require_llm: true
      })
      setResumeBatchResult(res.data || null)
      if (res.data?.ok) {
        message.success(`简历批量处理完成：导入 ${res.data?.imported || 0} 份`)
      } else {
        message.warning(res.data?.message || '批量处理未完全成功')
      }
      await loadSummary()
    } finally {
      setPipelineLoading(false)
    }
  }

  const runDebugLlmChat = async () => {
    setPipelineLoading(true)
    try {
      const res = await api.post('/admin/llm/chat_debug', {
        message: debugChatInput,
        json_mode: false
      })
      setDebugChatResult(res.data || null)
      if (res.data?.ok) {
        message.success('已完成一次模型直连对话')
      } else {
        message.warning('模型对话返回异常')
      }
      await loadSummary()
    } finally {
      setPipelineLoading(false)
    }
  }

  const exportSkillLabels = async () => {
    const values = await evalSkillForm.validateFields()
    const manualJobs = String(values.jobs || '')
      .split(',')
      .map((x: string) => x.trim())
      .filter(Boolean)
    const selectedJobs = Array.isArray(values.job_ids) ? values.job_ids.map((x: any) => String(x).trim()).filter(Boolean) : []
    const mergedJobs = Array.from(new Set([...manualJobs, ...selectedJobs]))

    const manualStudents = String(values.students || '')
      .split(',')
      .map((x: string) => x.trim())
      .filter(Boolean)
    const selectedStudents = Array.isArray(values.student_ids) ? values.student_ids.map((x: any) => String(x).trim()).filter(Boolean) : []
    const mergedStudents = Array.from(new Set([...manualStudents, ...selectedStudents]))

    setEvalLoading(true)
    try {
      const res = await api.post('/admin/eval/skill_match/export', {
        students: mergedStudents.join(','),
        jobs: mergedJobs.join(',')
      })
      setSkillLabelExport(res.data || null)
      message.success(`技能标注底表已导出，行数 ${res.data?.row_count || 0}`)
    } finally {
      setEvalLoading(false)
    }
  }

  const exportProfileLabels = async () => {
    const values = await evalProfileForm.validateFields()
    const manualStudents = String(values.students || '')
      .split(',')
      .map((x: string) => x.trim())
      .filter(Boolean)
    const selectedStudents = Array.isArray(values.student_ids) ? values.student_ids.map((x: any) => String(x).trim()).filter(Boolean) : []
    const mergedStudents = Array.from(new Set([...manualStudents, ...selectedStudents]))
    const manualJobs = String(values.jobs || '')
      .split(',')
      .map((x: string) => x.trim())
      .filter(Boolean)
    const selectedJobs = Array.isArray(values.job_ids) ? values.job_ids.map((x: any) => String(x).trim()).filter(Boolean) : []
    const mergedJobs = Array.from(new Set([...manualJobs, ...selectedJobs]))

    setEvalLoading(true)
    try {
      const res = await api.post('/admin/eval/profile/export', {
        students: mergedStudents.join(','),
        jobs: mergedJobs.join(','),
        random_jobs: values.random_jobs,
        random_students: values.random_students,
        seed: values.seed
      })
      setProfileLabelExport(res.data || null)
      message.success(`画像标注底表已导出，行数 ${res.data?.row_count || 0}`)
    } finally {
      setEvalLoading(false)
    }
  }

  const computeSkillEval = async () => {
    if (!skillEvalFile) {
      message.warning('请先选择技能标注 CSV')
      return
    }
    setEvalLoading(true)
    try {
      const data = new FormData()
      data.append('file', skillEvalFile)
      const res = await api.post('/admin/eval/skill_match/compute', data, {
        headers: { 'Content-Type': 'multipart/form-data' }
      })
      setSkillEvalResult(res.data || null)
      message.success(`技能匹配准确率计算完成：${((res.data?.accuracy || 0) * 100).toFixed(2)}%`)
    } finally {
      setEvalLoading(false)
    }
  }

  const computeProfileEval = async () => {
    if (!profileEvalFile) {
      message.warning('请先选择画像标注 CSV')
      return
    }
    setEvalLoading(true)
    try {
      const data = new FormData()
      data.append('file', profileEvalFile)
      const res = await api.post('/admin/eval/profile/compute', data, {
        headers: { 'Content-Type': 'multipart/form-data' }
      })
      setProfileEvalResult(res.data || null)
      message.success(`画像准确率计算完成：${((res.data?.accuracy || 0) * 100).toFixed(2)}%`)
    } finally {
      setEvalLoading(false)
    }
  }

  const previewColumns = (preview?.columns || []).map((name) => ({
    title: name,
    dataIndex: name,
    key: name,
    ellipsis: true,
    width: 180
  }))

  return (
    <div className="page-stack">
      <Card className="section-card">
        <div className="section-card-header">
          <div>
            <Text className="page-kicker">后台管理</Text>
            <Title level={3} style={{ marginTop: 4 }}>岗位、账号、导入和模型配置工作台</Title>
            <Paragraph type="secondary" style={{ marginBottom: 0 }}>
              本页用于岗位管理、账号权限、Excel 导入预览、模型配置和日志排查，并新增一键 AI 工作流面板。
            </Paragraph>
          </div>
        </div>
      </Card>

      <Row gutter={[16, 16]}>
        {statItems.map((item) => (
          <Col span={6} key={item.title}>
            <Card className="section-card">
              <Statistic title={item.title} value={item.value} />
            </Card>
          </Col>
        ))}
      </Row>

      <Tabs
        items={[
          {
            key: 'overview',
            label: '数据总览',
            children: (
              <Row gutter={[16, 16]}>
                <Col span={14}>
                  <Card className="section-card" title="系统概况">
                    <Descriptions column={2} bordered size="small">
                      <Descriptions.Item label="当前供应商">{String(summary.llm?.provider || '未配置')}</Descriptions.Item>
                      <Descriptions.Item label="当前模型">{String(summary.llm?.model || '未配置')}</Descriptions.Item>
                      <Descriptions.Item label="模型启用">{summary.llm?.enabled ? '是' : '否'}</Descriptions.Item>
                      <Descriptions.Item label="服务地址">{String(summary.llm?.base_url || '未配置')}</Descriptions.Item>
                    </Descriptions>
                  </Card>
                </Col>
                <Col span={10}>
                  <Card className="section-card" title="任务状态">
                    <Space wrap>
                      <Tag color="blue">待处理：{summary.tasks?.PENDING || 0}</Tag>
                      <Tag color="processing">执行中：{summary.tasks?.RUNNING || 0}</Tag>
                      <Tag color="green">成功：{summary.tasks?.SUCCESS || 0}</Tag>
                      <Tag color="red">失败：{summary.tasks?.FAILED || 0}</Tag>
                    </Space>
                  </Card>
                </Col>
              </Row>
            )
          },
          {
            key: 'jobs',
            label: '岗位管理',
            children: (
              <Card
                className="section-card"
                title="岗位数据台账"
                extra={(
                  <Space>
                    <Input.Search
                      allowClear
                      placeholder="按岗位ID/名称/公司搜索"
                      style={{ width: 260 }}
                      onSearch={(value) => {
                        void loadJobs({ page: 1, pageSize: jobPageSize, q: String(value || '').trim() })
                      }}
                    />
                    <Button type="primary" icon={<DatabaseOutlined />} onClick={() => openJobEditor()}>新增岗位</Button>
                  </Space>
                )}
              >
                <Table
                  rowKey="job_id"
                  columns={jobColumns}
                  dataSource={jobs}
                  scroll={{ x: 1200 }}
                  pagination={{
                    current: jobPage,
                    pageSize: jobPageSize,
                    total: jobTotal,
                    showSizeChanger: true,
                    pageSizeOptions: ['20', '50', '100', '200'],
                    showTotal: (total) => `共 ${total} 条`,
                    onChange: (page, pageSize) => {
                      void loadJobs({ page, pageSize, q: jobQuery })
                    }
                  }}
                />
              </Card>
            )
          },
          {
            key: 'users',
            label: '账号管理',
            children: (
              <Card className="section-card" title="账号与权限" extra={<Button type="primary" icon={<UserSwitchOutlined />} onClick={() => openUserEditor()}>新增账号</Button>}>
                <Table rowKey="user_id" columns={userColumns} dataSource={users} pagination={{ pageSize: 8 }} />
              </Card>
            )
          },
          {
            key: 'import',
            label: '数据导入',
            children: (
              <Space direction="vertical" size={16} style={{ width: '100%' }}>
                <Card className="section-card" title="Excel 导入预览" extra={<CloudUploadOutlined />}>
                  <Form layout="inline" form={importForm} initialValues={{ sheet_name: 0 }}>
                    <Form.Item label="工作表" name="sheet_name">
                      <Input style={{ width: 140 }} placeholder="默认 0" />
                    </Form.Item>
                    <Upload beforeUpload={(file) => { setSelectedFile(file); return false }} maxCount={1} showUploadList>
                      <Button>选择 Excel 文件</Button>
                    </Upload>
                    <Button type="primary" onClick={previewFile}>预览字段</Button>
                    <Button onClick={importFile}>正式导入</Button>
                  </Form>
                  <Paragraph type="secondary" style={{ marginTop: 12, marginBottom: 0 }}>
                    支持 .xls / .xlsx。建议先预览字段映射和样例，再正式入库。
                  </Paragraph>
                </Card>

                {preview ? (
                  <Row gutter={[16, 16]}>
                    <Col span={10}>
                      <Card className="section-card" title="导入摘要">
                        <Descriptions column={1} size="small" bordered>
                          <Descriptions.Item label="文件名">{preview.filename}</Descriptions.Item>
                          <Descriptions.Item label="工作表">{(preview.sheet_names || []).join('、') || '无'}</Descriptions.Item>
                          <Descriptions.Item label="字段数">{preview.columns?.length || 0}</Descriptions.Item>
                          <Descriptions.Item label="记录数">{preview.row_count || 0}</Descriptions.Item>
                        </Descriptions>
                      </Card>
                    </Col>
                    <Col span={14}>
                      <Card className="section-card" title="字段映射建议">
                        <Space wrap>
                          {(preview.mapped_fields || []).map((item) => (
                            <Tag key={item.source}>{item.source}{item.target ? ` -> ${item.target}` : ''}</Tag>
                          ))}
                        </Space>
                      </Card>
                    </Col>
                    <Col span={24}>
                      <Card className="section-card" title="样例数据">
                        <Table
                          rowKey={(_, index) => String(index)}
                          columns={previewColumns}
                          dataSource={preview.sample_rows || []}
                          scroll={{ x: 1200 }}
                          pagination={false}
                        />
                      </Card>
                    </Col>
                  </Row>
                ) : (
                  <Card className="section-card"><Empty description="请先选择 Excel 并点击预览字段" /></Card>
                )}
              </Space>
            )
          },
          {
            key: 'pipeline',
            label: 'AI工作流',
            children: (
              <Space direction="vertical" size={16} style={{ width: '100%' }}>
                <Row gutter={[16, 16]}>
                  <Col span={8}>
                    <Card className="section-card" title="岗位数据链路">
                      <Paragraph type="secondary">
                        基于 <Text code>20260226105856_457.xls</Text> 一键创建导入、画像、向量索引与图谱任务链。
                      </Paragraph>
                      <Button type="primary" block loading={pipelineLoading} onClick={runCompetitionXlsPipeline}>
                        一键启动岗位任务链
                      </Button>
                    </Card>
                  </Col>
                  <Col span={8}>
                    <Card className="section-card" title="简历AI画像（严格）">
                      <Paragraph type="secondary">
                        处理 10 份比赛简历并强制调用 LLM。若模型未启用会直接报错，不走规则兜底。
                      </Paragraph>
                      <Button block loading={pipelineLoading} onClick={runResumeBatchAiStrict}>
                        启动简历批量AI画像
                      </Button>
                    </Card>
                  </Col>
                  <Col span={8}>
                    <Card className="section-card" title="模型直连调试">
                      <Input
                        value={debugChatInput}
                        onChange={(e) => setDebugChatInput(e.target.value)}
                        placeholder="输入调试问题，例如：1+1=几？"
                        style={{ marginBottom: 10 }}
                      />
                      <Button block loading={pipelineLoading} onClick={runDebugLlmChat}>
                        发送到模型
                      </Button>
                    </Card>
                  </Col>
                </Row>

                {pipelineResult ? (
                  <Card className="section-card" title="岗位任务链结果">
                    <Descriptions bordered size="small" column={2}>
                      <Descriptions.Item label="源文件">{pipelineResult.source_path}</Descriptions.Item>
                      <Descriptions.Item label="Sheet">{String(pipelineResult.sheet_name ?? 0)}</Descriptions.Item>
                      <Descriptions.Item label="记录数">{pipelineResult.preview?.row_count || 0}</Descriptions.Item>
                      <Descriptions.Item label="任务数">{pipelineResult.task_ids?.length || 0}</Descriptions.Item>
                      <Descriptions.Item label="字段数">{pipelineResult.preview?.columns?.length || 0}</Descriptions.Item>
                      <Descriptions.Item label="任务ID样例">{(pipelineResult.task_ids || []).slice(0, 3).join(', ') || '-'}</Descriptions.Item>
                    </Descriptions>
                  </Card>
                ) : null}

                {resumeBatchResult ? (
                  <Card className="section-card" title="简历批量处理结果">
                    <Descriptions bordered size="small" column={2}>
                      <Descriptions.Item label="总数">{resumeBatchResult.total || 0}</Descriptions.Item>
                      <Descriptions.Item label="成功">{resumeBatchResult.imported || 0}</Descriptions.Item>
                      <Descriptions.Item label="失败">{resumeBatchResult.failed || 0}</Descriptions.Item>
                      <Descriptions.Item label="LLM启用">{resumeBatchResult.llm_enabled ? '是' : '否'}</Descriptions.Item>
                      <Descriptions.Item label="LLM严格模式">{resumeBatchResult.llm_required ? '是' : '否'}</Descriptions.Item>
                      <Descriptions.Item label="来源目录">{resumeBatchResult.source_root || '-'}</Descriptions.Item>
                    </Descriptions>
                  </Card>
                ) : null}

                {debugChatResult ? (
                  <Card className="section-card" title="模型调试返回">
                    <Paragraph style={{ marginBottom: 0 }}>
                      {typeof debugChatResult?.result === 'string'
                        ? debugChatResult.result
                        : JSON.stringify(debugChatResult?.result || {}, null, 2)}
                    </Paragraph>
                  </Card>
                ) : null}
              </Space>
            )
          },
          {
            key: 'evaluation',
            label: '评估验收',
            children: (
              <Space direction="vertical" size={16} style={{ width: '100%' }}>
                <Row gutter={[16, 16]}>
                  <Col span={12}>
                    <Card className="section-card" title="赛题阈值目标">
                      <Descriptions bordered size="small" column={1}>
                        <Descriptions.Item label="技能匹配准确率目标">{((evalGuide?.skill_match_accuracy?.target || 0.8) * 100).toFixed(0)}%</Descriptions.Item>
                        <Descriptions.Item label="画像字段准确率目标">{((evalGuide?.profile_accuracy?.target || 0.9) * 100).toFixed(0)}%</Descriptions.Item>
                      </Descriptions>
                    </Card>
                  </Col>
                  <Col span={12}>
                    <Card className="section-card" title="说明">
                      <Paragraph style={{ marginBottom: 8 }}>1. 先导出标注底表（第1步按钮）。</Paragraph>
                      <Paragraph style={{ marginBottom: 8 }}>
                        2. 在CSV里人工填写标注列：技能表填写 <Text code>true_match</Text>，画像表填写 <Text code>true_value</Text>。
                      </Paragraph>
                      <Paragraph style={{ marginBottom: 8 }}>3. 上传已标注CSV并点击计算（第2步、第3步按钮），看是否达到阈值目标。</Paragraph>
                      <Paragraph type="secondary" style={{ marginBottom: 0 }}>
                        原始技术字段会保留，但页面会先展示中文摘要，你不需要先读英文JSON。
                      </Paragraph>
                    </Card>
                  </Col>
                </Row>

                <Row gutter={[16, 16]}>
                  <Col span={12}>
                    <Card className="section-card" title="导出技能标注底表">
                      <Form form={evalSkillForm} layout="vertical" initialValues={{ students: '', student_ids: [], jobs: '', job_ids: [] }}>
                        <Form.Item label="学生ID（逗号分隔，可空）" name="students">
                          <Input placeholder="如 S001,S002" />
                        </Form.Item>
                        <Form.Item label="学生ID快速选择（可按姓名搜索）" name="student_ids">
                          <Select
                            mode="multiple"
                            allowClear
                            showSearch
                            options={studentIdOptions}
                            placeholder="可搜索姓名，例如 test赵、赵某某"
                            filterOption={false}
                            onSearch={(value) => { void loadStudents(String(value || '').trim()) }}
                          />
                        </Form.Item>
                        <Form.Item label="岗位ID快速选择（可多选）" name="job_ids">
                          <Select
                            mode="multiple"
                            allowClear
                            showSearch
                            options={jobIdOptions}
                            placeholder="从岗位台账直接选择，避免手工输入"
                            filterOption={false}
                            onSearch={(value) => { void loadJobOptions(String(value || '').trim()) }}
                          />
                        </Form.Item>
                        <Form.Item label="岗位ID（逗号分隔，可空）" name="jobs">
                          <Input placeholder="如 J001,J002" />
                        </Form.Item>
                        <Button type="primary" loading={evalLoading} onClick={exportSkillLabels}>第1步：导出技能标注CSV</Button>
                      </Form>
                      {skillLabelExport ? (
                        <>
                          <Paragraph style={{ marginTop: 12, marginBottom: 0 }}>
                            导出路径：{skillLabelExport.out_csv}
                          </Paragraph>
                          <Paragraph type="secondary" style={{ marginTop: 8, marginBottom: 8 }}>
                            预览已包含岗位ID字段 job_id，可直接核对你需要的岗位。
                          </Paragraph>
                          <Table
                            rowKey={(_, index) => String(index)}
                            columns={skillSampleColumns}
                            dataSource={skillSampleRows}
                            size="small"
                            scroll={{ x: 1100 }}
                            pagination={{ pageSize: 5 }}
                          />
                        </>
                      ) : null}
                    </Card>
                  </Col>
                  <Col span={12}>
                    <Card className="section-card" title="计算技能匹配准确率">
                      <Upload beforeUpload={(file) => { setSkillEvalFile(file); return false }} maxCount={1} showUploadList>
                        <Button>第2步：选择已标注技能CSV</Button>
                      </Upload>
                      <Button style={{ marginTop: 12 }} type="primary" loading={evalLoading} onClick={computeSkillEval}>第3步：计算技能准确率</Button>
                      {skillEvalResult ? (
                        <>
                          <Descriptions bordered size="small" column={2} style={{ marginTop: 12 }}>
                            <Descriptions.Item label="准确率">{formatPercent(skillEvalResult?.accuracy)}</Descriptions.Item>
                            <Descriptions.Item label="精确率">{formatPercent(skillEvalResult?.precision)}</Descriptions.Item>
                            <Descriptions.Item label="召回率">{formatPercent(skillEvalResult?.recall)}</Descriptions.Item>
                            <Descriptions.Item label="F1">{formatPercent(skillEvalResult?.f1)}</Descriptions.Item>
                            <Descriptions.Item label="样本数">{String(skillEvalResult?.row_count ?? skillEvalResult?.total ?? '-')}</Descriptions.Item>
                            <Descriptions.Item label="是否达标">
                              {Number(skillEvalResult?.accuracy ?? NaN) >= Number(evalGuide?.skill_match_accuracy?.target ?? 0.8) ? '是' : '否'}
                            </Descriptions.Item>
                          </Descriptions>
                          <details style={{ marginTop: 8 }}>
                            <summary>查看原始返回（技术字段）</summary>
                            <pre style={{ marginTop: 8, whiteSpace: 'pre-wrap' }}>{JSON.stringify(skillEvalResult, null, 2)}</pre>
                          </details>
                        </>
                      ) : null}
                    </Card>
                  </Col>
                </Row>

                <Row gutter={[16, 16]}>
                  <Col span={12}>
                    <Card className="section-card" title="导出画像标注底表">
                      <Form
                        form={evalProfileForm}
                        layout="vertical"
                        initialValues={{ students: '', student_ids: [], jobs: '', job_ids: [], random_jobs: 50, random_students: 50, seed: 42 }}
                      >
                        <Form.Item label="学生ID快速选择（可按姓名搜索）" name="student_ids">
                          <Select
                            mode="multiple"
                            allowClear
                            showSearch
                            options={studentIdOptions}
                            placeholder="可搜索姓名，例如 test赵、赵某某"
                            filterOption={false}
                            onSearch={(value) => { void loadStudents(String(value || '').trim()) }}
                          />
                        </Form.Item>
                        <Form.Item label="学生ID（逗号分隔，可空）" name="students">
                          <Input placeholder="如 S001,S002；为空表示不按学生ID过滤" />
                        </Form.Item>
                        <Form.Item label="岗位ID快速选择（可多选）" name="job_ids">
                          <Select
                            mode="multiple"
                            allowClear
                            showSearch
                            options={jobIdOptions}
                            placeholder="从岗位台账直接选择，避免手工输入"
                            filterOption={false}
                            onSearch={(value) => { void loadJobOptions(String(value || '').trim()) }}
                          />
                        </Form.Item>
                        <Form.Item label="岗位ID（逗号分隔，可空）" name="jobs">
                          <Input placeholder="如 J001,J002；为空表示不按岗位ID过滤" />
                        </Form.Item>
                        <Row gutter={12}>
                          <Col span={8}>
                            <Form.Item label="岗位抽样条数" name="random_jobs">
                              <InputNumber min={0} style={{ width: '100%' }} />
                            </Form.Item>
                          </Col>
                          <Col span={8}>
                            <Form.Item label="学生抽样条数" name="random_students">
                              <InputNumber min={0} style={{ width: '100%' }} />
                            </Form.Item>
                          </Col>
                          <Col span={8}>
                            <Form.Item label="随机种子（复现实验）" name="seed">
                              <InputNumber min={0} style={{ width: '100%' }} />
                            </Form.Item>
                          </Col>
                        </Row>
                        <Button type="primary" loading={evalLoading} onClick={exportProfileLabels}>第1步：导出画像标注CSV</Button>
                      </Form>
                      {profileLabelExport ? (
                        <>
                          <Paragraph style={{ marginTop: 12, marginBottom: 0 }}>
                            导出路径：{profileLabelExport.out_csv}
                          </Paragraph>
                          <Paragraph type="secondary" style={{ marginTop: 8, marginBottom: 8 }}>
                            画像标注预览中，岗位ID与学生ID都位于 entity_id 字段：entity_type=job 为岗位ID，entity_type=student 为学生ID。
                          </Paragraph>
                          <Table
                            rowKey={(_, index) => String(index)}
                            columns={profileSampleColumns}
                            dataSource={profileSampleRows}
                            size="small"
                            scroll={{ x: 1100 }}
                            pagination={{ pageSize: 5 }}
                          />
                        </>
                      ) : null}
                    </Card>
                  </Col>
                  <Col span={12}>
                    <Card className="section-card" title="计算画像字段准确率">
                      <Upload beforeUpload={(file) => { setProfileEvalFile(file); return false }} maxCount={1} showUploadList>
                        <Button>第2步：选择已标注画像CSV</Button>
                      </Upload>
                      <Button style={{ marginTop: 12 }} type="primary" loading={evalLoading} onClick={computeProfileEval}>第3步：计算画像准确率</Button>
                      {profileEvalResult ? (
                        <>
                          <Descriptions bordered size="small" column={2} style={{ marginTop: 12 }}>
                            <Descriptions.Item label="准确率">{formatPercent(profileEvalResult?.accuracy)}</Descriptions.Item>
                            <Descriptions.Item label="精确率">{formatPercent(profileEvalResult?.precision)}</Descriptions.Item>
                            <Descriptions.Item label="召回率">{formatPercent(profileEvalResult?.recall)}</Descriptions.Item>
                            <Descriptions.Item label="F1">{formatPercent(profileEvalResult?.f1)}</Descriptions.Item>
                            <Descriptions.Item label="样本数">{String(profileEvalResult?.row_count ?? profileEvalResult?.total ?? '-')}</Descriptions.Item>
                            <Descriptions.Item label="是否达标">
                              {Number(profileEvalResult?.accuracy ?? NaN) >= Number(evalGuide?.profile_accuracy?.target ?? 0.9) ? '是' : '否'}
                            </Descriptions.Item>
                          </Descriptions>
                          <details style={{ marginTop: 8 }}>
                            <summary>查看原始返回（技术字段）</summary>
                            <pre style={{ marginTop: 8, whiteSpace: 'pre-wrap' }}>{JSON.stringify(profileEvalResult, null, 2)}</pre>
                          </details>
                        </>
                      ) : null}
                    </Card>
                  </Col>
                </Row>
              </Space>
            )
          },
          {
            key: 'llm',
            label: '模型接入',
            children: (
              <Card className="section-card" title="外部大模型配置">
                <Row gutter={[16, 16]}>
                  <Col span={15}>
                    <Form layout="vertical" form={llmForm}>
                      <Row gutter={16}>
                        <Col span={12}>
                          <Form.Item label="供应商" name="provider" rules={[{ required: true, message: '请选择供应商' }]}>
                            <Select options={providers.map((item) => ({ label: item.label, value: item.provider }))} />
                          </Form.Item>
                        </Col>
                        <Col span={12}>
                          <Form.Item label="启用外部模型" name="enabled" valuePropName="checked">
                            <Switch checkedChildren="开启" unCheckedChildren="关闭" />
                          </Form.Item>
                        </Col>
                        <Col span={24}>
                          <Form.Item label="服务地址" name="base_url" rules={[{ required: true, message: '请填写服务地址' }]}>
                            <Input />
                          </Form.Item>
                        </Col>
                        <Col span={12}>
                          <Form.Item label="模型名" name="model" rules={[{ required: true, message: '请填写模型名' }]}>
                            <Input />
                          </Form.Item>
                        </Col>
                        <Col span={12}>
                          <Form.Item label="访问密钥" name="api_key">
                            <Input.Password placeholder="留空表示沿用已有密钥" />
                          </Form.Item>
                        </Col>
                        <Col span={12}>
                          <Form.Item label="超时（秒）" name="timeout_seconds">
                            <InputNumber min={10} max={300} style={{ width: '100%' }} />
                          </Form.Item>
                        </Col>
                        <Col span={12}>
                          <Form.Item label="温度" name="temperature">
                            <InputNumber min={0} max={1} step={0.1} style={{ width: '100%' }} />
                          </Form.Item>
                        </Col>
                      </Row>
                      <Space>
                        <Button type="primary" icon={<SettingOutlined />} onClick={saveLlm}>保存配置</Button>
                        <Button loading={testing} onClick={testLlm}>测试连通</Button>
                        <Button onClick={applyZhipuPreset}>套用智谱GLM-4.5-Air</Button>
                        <Button loading={quickLlmLoading} onClick={runQuickLlmSmokeTest}>1+1 冒烟测试</Button>
                      </Space>
                    </Form>
                  </Col>
                  <Col span={9}>
                    <Card size="small" title="配置说明">
                      <Paragraph>
                        智谱兼容接口建议：<Text code>https://open.bigmodel.cn/api/paas/v4</Text>，模型如 <Text code>glm-4.5-air</Text>。
                      </Paragraph>
                      <Paragraph type="secondary" style={{ marginBottom: 0 }}>
                        当前选择：{selectedProvider || '未选择'}
                      </Paragraph>
                    </Card>
                  </Col>
                </Row>
              </Card>
            )
          },
          {
            key: 'logs',
            label: '调用日志',
            children: (
              <Row gutter={[16, 16]}>
                <Col span={12}>
                  <Card className="section-card" title="模型调用日志">
                    <Space direction="vertical" style={{ width: '100%' }}>
                      {llmLogs.map((item, idx) => (
                        <Card key={idx} size="small" title={item?.trace_id || item?.load_id || '模型调用'}>
                          <Paragraph style={{ marginBottom: 8 }}>供应商：{item?.provider || '-'} / 模型：{item?.model || '-'}</Paragraph>
                          <Paragraph style={{ marginBottom: 8 }}>结果：{item?.ok ? '成功' : '失败'} / 耗时：{item?.duration_ms || 0} ms</Paragraph>
                          <Paragraph style={{ marginBottom: 8 }}>上下文：{item?.trace_context || '-'}</Paragraph>
                          <Paragraph type="secondary" ellipsis={{ rows: 3, expandable: true, symbol: '展开' }}>{JSON.stringify(item?.input || {}, null, 2)}</Paragraph>
                        </Card>
                      ))}
                    </Space>
                  </Card>
                </Col>
                <Col span={12}>
                  <Card className="section-card" title="运行日志">
                    <Space direction="vertical" style={{ width: '100%' }}>
                      {appLogs.map((item, idx) => (
                        <Card key={idx} size="small" title={item?.time || '运行日志'}>
                          <Paragraph style={{ marginBottom: 0 }}>{item?.message || JSON.stringify(item)}</Paragraph>
                        </Card>
                      ))}
                    </Space>
                  </Card>
                </Col>
              </Row>
            )
          }
        ]}
      />

      <Drawer
        title={editingJob ? '编辑岗位' : '新增岗位'}
        open={jobDrawerOpen}
        onClose={closeJobDrawer}
        width={560}
        zIndex={1100}
        extra={<Button type="primary" loading={saving} onClick={saveJob}>保存</Button>}
      >
        {jobEditorLoading ? <Paragraph type="secondary">正在加载岗位详情与画像...</Paragraph> : null}
        <Form layout="vertical" form={jobForm}>
          <Form.Item label="岗位名称" name="title" rules={[{ required: true, message: '请输入岗位名称' }]}>
            <Input />
          </Form.Item>
          <Form.Item label="工作地点" name="location"><Input /></Form.Item>
          <Form.Item label="公司名称" name="company_name"><Input /></Form.Item>
          <Form.Item label="所属行业" name="industry"><Input /></Form.Item>
          <Form.Item label="岗位编码" name="job_code"><Input /></Form.Item>
          <Form.Item label="岗位来源链接" name="source_url"><Input /></Form.Item>
          <Row gutter={16}>
            <Col span={12}><Form.Item label="最低薪资" name="salary_min"><InputNumber style={{ width: '100%' }} /></Form.Item></Col>
            <Col span={12}><Form.Item label="最高薪资" name="salary_max"><InputNumber style={{ width: '100%' }} /></Form.Item></Col>
          </Row>
          <Form.Item label="薪资周期" name="salary_period"><Select options={[{ label: '按月', value: 'month' }, { label: '按年', value: 'year' }, { label: '按天', value: 'day' }]} /></Form.Item>
          <Form.Item label="公司简介" name="company_intro"><Input.TextArea rows={3} /></Form.Item>
          <Form.Item label="岗位描述" name="description"><Input.TextArea rows={6} /></Form.Item>
          <Card size="small" title="岗位画像（可手工编辑）" style={{ marginBottom: 12 }}>
            <Form.Item label="岗位族" name="profile_job_family"><Input placeholder="如 backend / frontend / ops" /></Form.Item>
            <Form.Item label="硬技能" name="profile_hard_skills">
              <Select mode="tags" tokenSeparators={[',', '，']} placeholder="输入后回车，可填多个" />
            </Form.Item>
            <Form.Item label="软技能" name="profile_soft_skills">
              <Select mode="tags" tokenSeparators={[',', '，']} placeholder="输入后回车，可填多个" />
            </Form.Item>
            <Form.Item label="证书" name="profile_certificates">
              <Select mode="tags" tokenSeparators={[',', '，']} placeholder="输入后回车，可填多个" />
            </Form.Item>
            <Form.Item label="标签" name="profile_tags">
              <Select mode="tags" tokenSeparators={[',', '，']} placeholder="输入后回车，可填多个" />
            </Form.Item>
            <Row gutter={16}>
              <Col span={12}><Form.Item label="学历要求" name="profile_education"><Input placeholder="如 本科" /></Form.Item></Col>
              <Col span={12}><Form.Item label="经验下限（年）" name="profile_experience_years_min"><InputNumber min={0} style={{ width: '100%' }} /></Form.Item></Col>
            </Row>
            <Form.Item label="保存后自动重算画像" name="auto_generate_profile" valuePropName="checked" initialValue={false}>
              <Switch checkedChildren="自动" unCheckedChildren="手工" />
            </Form.Item>
          </Card>
        </Form>
      </Drawer>

      <Drawer
        title={editingUser ? '编辑账号' : '新增账号'}
        open={userDrawerOpen}
        onClose={closeUserDrawer}
        width={480}
        zIndex={1100}
        extra={<Button type="primary" loading={saving} onClick={saveUser}>保存</Button>}
      >
        <Form layout="vertical" form={userForm}>
          <Form.Item label="账号" name="username" rules={[{ required: true, message: '请输入账号' }]}><Input /></Form.Item>
          <Form.Item label="显示名称" name="display_name" rules={[{ required: true, message: '请输入显示名称' }]}><Input /></Form.Item>
          <Form.Item label="权限" name="role" rules={[{ required: true, message: '请选择权限' }]}>
            <Select options={[{ label: '系统管理员', value: 'admin' }, { label: '就业老师', value: 'operator' }, { label: '展示账号', value: 'viewer' }, { label: '个人用户', value: 'student' }]} />
          </Form.Item>
          <Form.Item label="密码（新增必填，编辑留空表示不修改）" name="password"><Input.Password /></Form.Item>
          <Form.Item label="启用状态" name="is_active" valuePropName="checked"><Switch checkedChildren="启用" unCheckedChildren="停用" /></Form.Item>
        </Form>
      </Drawer>

      <Drawer
        title={activeJobProfile?.job?.title || activeJobProfile?.job?.job_id || '岗位画像详情'}
        open={jobProfileDrawerOpen}
        onClose={closeJobProfileDrawer}
        width={680}
        zIndex={1200}
      >
        {jobProfileLoading ? <Paragraph type="secondary">岗位画像加载中...</Paragraph> : null}
        {activeJobProfile?.error ? <Paragraph type="danger">{String(activeJobProfile.error)}</Paragraph> : null}
        {activeJobProfile ? (
          <Space direction="vertical" size={16} style={{ width: '100%' }}>
            <Card size="small" title="岗位信息">
              <Descriptions size="small" bordered column={1}>
                <Descriptions.Item label="岗位ID">{activeJobProfile?.job?.job_id || '-'}</Descriptions.Item>
                <Descriptions.Item label="岗位名称">{activeJobProfile?.job?.title || '-'}</Descriptions.Item>
                <Descriptions.Item label="公司">{activeJobProfile?.job?.company_name || '-'}</Descriptions.Item>
                <Descriptions.Item label="地点">{activeJobProfile?.job?.location || '-'}</Descriptions.Item>
                <Descriptions.Item label="薪资">{salaryText(activeJobProfile?.job || {})}</Descriptions.Item>
              </Descriptions>
            </Card>

            {activeJobProfile?.profile?.profile ? (
              <Card size="small" title="岗位画像">
                <Space direction="vertical" size={10} style={{ width: '100%' }}>
                  <div>
                    <Text strong>岗位族：</Text>
                    <Tag style={{ marginLeft: 8 }}>{String(activeJobProfile?.profile?.profile?.job_family_label || activeJobProfile?.profile?.profile?.job_family || '-')}</Tag>
                  </div>
                  <div>
                    <Text strong>硬技能：</Text>
                    <div style={{ marginTop: 8 }}>
                      {normalizeProfileTags(activeJobProfile?.profile?.profile?.hard_skills, ['mention', 'name', 'skill_id']).map((name) => (
                        <Tag key={`hard-${name}`}>{name}</Tag>
                      ))}
                    </div>
                  </div>
                  <div>
                    <Text strong>软技能：</Text>
                    <div style={{ marginTop: 8 }}>
                      {normalizeProfileTags(activeJobProfile?.profile?.profile?.soft_skills, ['name', 'mention', 'soft_skill_id']).map((name) => (
                        <Tag key={`soft-${name}`}>{name}</Tag>
                      ))}
                    </div>
                  </div>
                  <div>
                    <Text strong>证书：</Text>
                    <div style={{ marginTop: 8 }}>
                      {normalizeProfileTags(activeJobProfile?.profile?.profile?.certificates, ['name', 'certificate_id']).map((name) => (
                        <Tag key={`cert-${name}`}>{name}</Tag>
                      ))}
                    </div>
                  </div>
                  <div>
                    <Text strong>学历要求：</Text>
                    <Text style={{ marginLeft: 8 }}>{activeJobProfile?.profile?.profile?.basic_requirements?.education || '-'}</Text>
                  </div>
                  <div>
                    <Text strong>经验要求：</Text>
                    <Text style={{ marginLeft: 8 }}>
                      {activeJobProfile?.profile?.profile?.basic_requirements?.experience_years_min === null || activeJobProfile?.profile?.profile?.basic_requirements?.experience_years_min === undefined
                        ? '-'
                        : `${activeJobProfile?.profile?.profile?.basic_requirements?.experience_years_min} 年+`}
                    </Text>
                  </div>
                  <div>
                    <Text strong>标签：</Text>
                    <div style={{ marginTop: 8 }}>
                      {normalizeProfileTags(activeJobProfile?.profile?.profile?.tags, ['name']).map((name) => (
                        <Tag key={`tag-${name}`} color="blue">{name}</Tag>
                      ))}
                    </div>
                  </div>
                </Space>
              </Card>
            ) : (
              <Card size="small">
                <Empty description="该岗位暂无画像数据" image={Empty.PRESENTED_IMAGE_SIMPLE} />
              </Card>
            )}
          </Space>
        ) : null}
      </Drawer>
    </div>
  )
}
