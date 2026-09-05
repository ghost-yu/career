import React, { useEffect, useMemo, useState } from 'react'
import { Alert, App, Button, Card, Col, Form, Input, InputNumber, Modal, Progress, Radio, Row, Select, Space, Statistic, Tag, Typography, Upload } from 'antd'
import type { UploadProps } from 'antd'
import { InboxOutlined, MinusCircleOutlined, PlusOutlined } from '@ant-design/icons'
import { api } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { familyChoiceOptions, familyLabel, normalizeFamily } from '../constants/labels'
import { presentReportLabel, presentStudentOption } from '../utils/present'

const { Dragger } = Upload
const { Title, Text } = Typography

const MBTI_OPTIONS = [
  'INTJ', 'INTP', 'ENTJ', 'ENTP',
  'INFJ', 'INFP', 'ENFJ', 'ENFP',
  'ISTJ', 'ISFJ', 'ESTJ', 'ESFJ',
  'ISTP', 'ISFP', 'ESTP', 'ESFP'
].map((value) => ({ label: value, value }))

const SOURCE_LABELS: Record<string, string> = {
  llm: 'AI',
  manual: '手动',
  questionnaire: '测评',
  rule: '规则',
  rule_text: '规则(文本)',
  rule_section: '规则(分区)',
  rule_explicit: '规则(显式数字)',
  primary: '主来源',
  secondary: '次来源',
  mixed: '混合'
}

const PROFICIENCY_OPTIONS = [
  { label: '了解', value: 'aware' },
  { label: '熟悉', value: 'familiar' },
  { label: '熟练', value: 'proficient' },
  { label: '项目实战', value: 'project' },
  { label: '可独立交付', value: 'delivery' }
]

const proficiencyLabel = (value: any) => {
  const raw = String(value || '').trim()
  return PROFICIENCY_OPTIONS.find(item => item.value === raw || item.label === raw)?.label || raw || '可独立交付'
}

const normalizeHardSkillRows = (value: any): any[] => {
  const rows = Array.isArray(value) ? value : []
  return rows
    .map((item: any) => {
      if (typeof item === 'string') return { name: item, proficiency: 'delivery' }
      return {
        name: String(item?.name || item?.mention || item?.skill || '').trim(),
        proficiency: String(item?.proficiency || item?.level || 'delivery').trim() || 'delivery'
      }
    })
    .filter((item: any) => item.name)
}

type MBTIQuestionItem = {
  id: number
  question: string
  choice_a: { value: string, text: string }
  choice_b: { value: string, text: string }
}

type ExperienceDetailItem = {
  content?: string
  evidence?: string
}

const isRulePlaceholderLine = (line: string): boolean => {
  const text = String(line || '').trim()
  if (!text) return true
  return /规则抽取|自动抽取|每行一条|可编辑/.test(text)
}

const splitReadableLines = (value: any): string[] => {
  const text = String(value || '')
    .replace(/\r/g, '\n')
    .replace(/\u3000/g, ' ')
    .trim()
  if (!text) return []

  const sentences = text
    .split(/[\n；;。！？!?]+/)
    .map((line) => line.trim())
    .filter(Boolean)

  const fine: string[] = []
  for (const sentence of sentences) {
    const chunks = sentence
      .split(/[，,、]+/)
      .map((line) => line.trim())
      .filter(Boolean)
    if (chunks.length <= 1) {
      fine.push(sentence)
      continue
    }
    // 短句按逗号拆分可显著提升可读性；过短片段会被过滤。
    chunks.forEach((item) => {
      if (item.length >= 4) fine.push(item)
    })
  }
  return fine.length ? fine : sentences
}

const splitReadableCollection = (value: any): string[] => {
  if (!Array.isArray(value)) return splitReadableLines(value)
  return value
    .flatMap((item) => splitReadableLines(item))
    .map((item) => item.trim())
    .filter(Boolean)
}

const buildExperienceItemKey = (field: string, content: string, evidence: string): string => {
  const raw = `${content}\n${evidence}`.replace(/\s+/g, '').toLowerCase()
  if (!raw) return ''
  if (field === 'awards') {
    return raw
      .replace(/获得|荣获|获|证书|荣誉|奖项|奖励|竞赛|比赛|大赛/g, '')
      .slice(0, 120)
  }
  const date = raw.match(/(20\d{2}[./-]?\d{1,2})\s*(?:-|~|—|–|至|到)\s*(20\d{2}[./-]?\d{1,2}|至今|present|now)/i)?.[0] || ''
  const org = raw.match(/[a-z0-9\u4e00-\u9fff（）()·\-_]{2,40}(?:公司|集团|大学|学院|研究院|研究所|实验室|学校|医院|银行|政府|中心|委员会|inc|ltd|limited)/i)?.[0] || ''
  return `${field}:${date}:${org}:${raw.slice(0, 80)}`
}

const toExperienceDetailItems = (itemsRaw: any, evidenceRaw: any, field: string = 'general'): ExperienceDetailItem[] => {
  const out: ExperienceDetailItem[] = []
  const seen = new Set<string>()
  const push = (content: any, evidence: any) => {
    const c = String(content || '').trim()
    const e = String(evidence || '').trim()
    if (!c && !e) return
    const contentText = c || (e ? e.slice(0, 80) : '')
    const evidenceText = e || (field === 'awards' ? '' : contentText)
    if (!contentText) return
    if (field !== 'awards' && !evidenceText) return
    if (isRulePlaceholderLine(contentText) || (evidenceText && isRulePlaceholderLine(evidenceText))) return
    const key = buildExperienceItemKey(field, contentText, evidenceText)
    if (seen.has(key)) return
    seen.add(key)
    out.push({ content: contentText.slice(0, 180), evidence: evidenceText.slice(0, 300) })
  }

  if (Array.isArray(itemsRaw)) {
    itemsRaw.forEach((item) => {
      if (item && typeof item === 'object') {
        push(
          (item as any).content || (item as any).item || (item as any).summary || (item as any).title || (item as any).name || '',
          (item as any).evidence || (item as any).proof || (item as any).source_text || ''
        )
        return
      }
      const text = String(item || '').trim()
      if (text) push(text, field === 'awards' ? '' : text)
    })
  }
  if (!out.length && Array.isArray(evidenceRaw)) {
    evidenceRaw.forEach((line) => {
      const text = String(line || '').trim()
      if (text) push(text.slice(0, 80), field === 'awards' ? '' : text)
    })
  }
  return out.slice(0, 8)
}

const sanitizeExperienceDetailItems = (value: any, field: string = 'general'): ExperienceDetailItem[] => {
  return toExperienceDetailItems(value, [], field)
}

const toEvidenceListFromItems = (value: any, field: string = 'general'): string[] => {
  return sanitizeExperienceDetailItems(value, field)
    .map((item) => {
      if (field === 'awards') return String(item.content || '').trim()
      return String(item.evidence || item.content || '').trim()
    })
    .filter((line) => line.length >= (field === 'awards' ? 2 : 4))
    .slice(0, 8)
}

const experienceCountFromItems = (value: any, field: string = 'general'): number => {
  return sanitizeExperienceDetailItems(value, field).length
}

export default function StudentWorkspace() {
  const { message } = App.useApp()
  const { canWrite, user } = useAuth()
  const personal = user?.role === 'student'
  const [students, setStudents] = useState<any[]>([])
  const [studentId, setStudentId] = useState('')
  const [studentName, setStudentName] = useState('')
  const [profile, setProfile] = useState<any>(null)
  const [reports, setReports] = useState<any[]>([])
  const [loading, setLoading] = useState(false)
  const [creatingStudent, setCreatingStudent] = useState(false)
  const [createOpen, setCreateOpen] = useState(false)
  const [newStudentId, setNewStudentId] = useState('')
  const [newStudentName, setNewStudentName] = useState('')
  const [mbtiQuizOpen, setMbtiQuizOpen] = useState(false)
  const [mbtiQuestions, setMbtiQuestions] = useState<MBTIQuestionItem[]>([])
  const [mbtiAnswers, setMbtiAnswers] = useState<Record<number, string>>({})
  const [mbtiIndex, setMbtiIndex] = useState(0)
  const [mbtiQuizLoading, setMbtiQuizLoading] = useState(false)
  const [form] = Form.useForm()
  const internshipsItemsWatch = Form.useWatch('internships_items', form)
  const projectsItemsWatch = Form.useWatch('projects_items', form)
  const awardsItemsWatch = Form.useWatch('awards_items', form)
  const openSourceItemsWatch = Form.useWatch('open_source_items', form)
  const leadershipItemsWatch = Form.useWatch('leadership_items', form)

  const derivedExperienceCounts = useMemo(() => ({
    internships: experienceCountFromItems(internshipsItemsWatch, 'internships'),
    projects: experienceCountFromItems(projectsItemsWatch, 'projects'),
    awards: experienceCountFromItems(awardsItemsWatch, 'awards'),
    open_source: experienceCountFromItems(openSourceItemsWatch, 'open_source'),
    leadership: experienceCountFromItems(leadershipItemsWatch, 'leadership'),
  }), [internshipsItemsWatch, projectsItemsWatch, awardsItemsWatch, openSourceItemsWatch, leadershipItemsWatch])

  const extractionMeta = profile?.extraction_meta || {}
  const fieldSources = extractionMeta?.experience_field_sources || {}
  const evidenceMap = extractionMeta?.experience_evidence || {}
  const detailItemsMap = extractionMeta?.experience_detail_items || {}
  const sourceTag = (key: string) => SOURCE_LABELS[String(fieldSources?.[key] || extractionMeta?.experience_counter_source || '').trim()] || String(fieldSources?.[key] || extractionMeta?.experience_counter_source || '未知')

  const loadStudents = async (keyword: string = '') => {
    const res = await api.get('/students', {
      params: { limit: 200, offset: 0, q: keyword || undefined }
    })
    const items = res.data.items || []
    setStudents(items)
    if (!studentId && items.length) {
      setStudentId(String(items[0].student_id || ''))
    }
  }

  const loadStudent = async (sid: string) => {
    if (!sid) return
    const res = await api.get(`/students/${sid}`)
    if (res.data?.student) {
      setStudentName(res.data.student.name || '')
      setProfile(res.data.profile?.profile || null)
      setReports(res.data.reports || [])
      const p = res.data.profile?.profile || {}
      const extraction = p.extraction_meta || {}
      const expEvidence = extraction.experience_evidence || {}
      const expDetailItems = extraction.experience_detail_items || {}
      const internshipsItems = toExperienceDetailItems(expDetailItems?.internships, expEvidence?.internships, 'internships')
      const projectsItems = toExperienceDetailItems(expDetailItems?.projects, expEvidence?.projects, 'projects')
      const awardsItems = toExperienceDetailItems(expDetailItems?.awards, expEvidence?.awards, 'awards')
      const openSourceItems = toExperienceDetailItems(expDetailItems?.open_source, expEvidence?.open_source, 'open_source')
      const leadershipItems = toExperienceDetailItems(expDetailItems?.leadership, expEvidence?.leadership, 'leadership')
      form.setFieldsValue({
        mbti_type: p.mbti_type || undefined,
        hard_skills: normalizeHardSkillRows(p.hard_skills || []),
        soft_skills: (p.soft_skills || []).map((x: any) => x.name),
        certificates: (p.certificates || []).map((x: any) => x.name),
        preferred_locations: p.preferences?.preferred_locations || [],
        preferred_job_families: p.preferences?.preferred_job_families || [],
        target_salary_min: p.preferences?.target_salary_min,
        target_salary_max: p.preferences?.target_salary_max,
        internships: internshipsItems.length,
        projects: projectsItems.length,
        awards: awardsItems.length,
        open_source: openSourceItems.length,
        leadership: leadershipItems.length,
        internships_items: internshipsItems,
        projects_items: projectsItems,
        awards_items: awardsItems,
        open_source_items: openSourceItems,
        leadership_items: leadershipItems,
        raw_text: p.profile_notes || p.preferences?.notes || ''
      })
    }
  }

  useEffect(() => { void loadStudents() }, [])
  useEffect(() => { void loadStudent(studentId) }, [studentId])
  useEffect(() => {
    form.setFieldsValue({
      internships: derivedExperienceCounts.internships,
      projects: derivedExperienceCounts.projects,
      awards: derivedExperienceCounts.awards,
      open_source: derivedExperienceCounts.open_source,
      leadership: derivedExperienceCounts.leadership,
    })
  }, [derivedExperienceCounts, form])

  const studentOptions = useMemo(() => {
    return students.map((s, index) => ({ label: presentStudentOption(s, index), value: s.student_id }))
  }, [students])

  const buildAutoStudentId = () => {
    const now = new Date()
    const stamp = [
      now.getFullYear(),
      String(now.getMonth() + 1).padStart(2, '0'),
      String(now.getDate()).padStart(2, '0'),
      String(now.getHours()).padStart(2, '0'),
      String(now.getMinutes()).padStart(2, '0'),
      String(now.getSeconds()).padStart(2, '0')
    ].join('')
    const random = Math.floor(Math.random() * 9000) + 1000
    return `S${stamp}${random}`
  }

  const buildDefaultStudentName = () => {
    const now = new Date()
    const yyyy = now.getFullYear()
    const mm = String(now.getMonth() + 1).padStart(2, '0')
    const dd = String(now.getDate()).padStart(2, '0')
    const hh = String(now.getHours()).padStart(2, '0')
    const mi = String(now.getMinutes()).padStart(2, '0')
    const ss = String(now.getSeconds()).padStart(2, '0')
    return `${yyyy}-${mm}-${dd} ${hh}:${mi}:${ss}`
  }

  const openCreateStudent = () => {
    if (!canWrite) {
      message.warning('只读角色不可新增学生。')
      return
    }
    setNewStudentId(buildAutoStudentId())
    setNewStudentName(personal ? (user?.display_name || user?.username || '') : buildDefaultStudentName())
    setCreateOpen(true)
  }

  const createStudent = async () => {
    if (!canWrite) {
      message.warning('只读角色不可新增学生。')
      return
    }
    const name = String(newStudentName || '').trim() || buildDefaultStudentName()
    setCreatingStudent(true)
    try {
      let sid = String(newStudentId || '').trim() || buildAutoStudentId()
      let created = false
      let lastDetail = ''
      for (let attempt = 0; attempt < 5; attempt += 1) {
        try {
          await api.post('/students', { student_id: sid, name: name || null })
          created = true
          break
        } catch (e: any) {
          const detail = String(e?.response?.data?.detail || e?.message || '')
          lastDetail = detail
          if (detail.includes('UNIQUE') || detail.includes('already')) {
            sid = buildAutoStudentId()
            setNewStudentId(sid)
            continue
          }
          throw e
        }
      }
      if (!created) {
        throw new Error(lastDetail || '创建学生失败')
      }
      await loadStudents()
      setStudentId(sid)
      setCreateOpen(false)
      message.success(`已新增学生档案 ${sid}`)
    } catch (e: any) {
      const detail = String(e?.response?.data?.detail || e?.message || '')
      if (detail.includes('UNIQUE') || detail.includes('already')) {
        message.error('学生ID已存在，请更换')
      } else if (detail === 'personal_profile_limit') {
        message.warning('每个账号只能建立一份画像，请编辑已有画像。')
      } else {
        message.error(`新增失败：${detail || '请求失败'}`)
      }
    } finally {
      setCreatingStudent(false)
    }
  }

  const saveManualProfile = async () => {
    if (!canWrite) {
      message.warning('只读角色不可保存画像。')
      return
    }
    const values = await form.validateFields()
    const preferredJobFamilies = Array.from(new Set(
      (values.preferred_job_families || [])
        .map((item: string) => normalizeFamily(item))
        .map((item: string) => String(item || '').trim())
        .filter(Boolean)
    ))
    setLoading(true)
    try {
      const experienceDetailItems = {
        internships: sanitizeExperienceDetailItems(values.internships_items, 'internships'),
        projects: sanitizeExperienceDetailItems(values.projects_items, 'projects'),
        awards: sanitizeExperienceDetailItems(values.awards_items, 'awards'),
        open_source: sanitizeExperienceDetailItems(values.open_source_items, 'open_source'),
        leadership: sanitizeExperienceDetailItems(values.leadership_items, 'leadership')
      }
      await api.post(`/students/${studentId}/profile/manual`, {
        name: studentName,
        mbti_type: values.mbti_type || null,
        hard_skills: normalizeHardSkillRows(values.hard_skills),
        soft_skills: values.soft_skills || [],
        certificates: values.certificates || [],
        raw_text: values.raw_text,
        experience: {
          internships: derivedExperienceCounts.internships,
          projects: derivedExperienceCounts.projects,
          awards: derivedExperienceCounts.awards,
          open_source: derivedExperienceCounts.open_source,
          leadership: derivedExperienceCounts.leadership
        },
        experience_detail_items: experienceDetailItems,
        experience_details: {
          internships: toEvidenceListFromItems(experienceDetailItems.internships, 'internships'),
          projects: toEvidenceListFromItems(experienceDetailItems.projects, 'projects'),
          awards: toEvidenceListFromItems(experienceDetailItems.awards, 'awards'),
          open_source: toEvidenceListFromItems(experienceDetailItems.open_source, 'open_source'),
          leadership: toEvidenceListFromItems(experienceDetailItems.leadership, 'leadership')
        },
        preferences: {
          preferred_locations: values.preferred_locations || [],
          preferred_job_families: preferredJobFamilies,
          target_salary_min: values.target_salary_min,
          target_salary_max: values.target_salary_max,
          notes: values.notes
        }
      })
      message.success('学生画像已保存')
      await loadStudents()
      await loadStudent(studentId)
    } finally {
      setLoading(false)
    }
  }

  const buildProfileHintsForGenerate = () => {
    const values = form.getFieldsValue()
    const preferredJobFamilies = Array.from(new Set(
      (values.preferred_job_families || [])
        .map((item: string) => normalizeFamily(item))
        .map((item: string) => String(item || '').trim())
        .filter(Boolean)
    ))
    const experienceDetailItems = {
      internships: sanitizeExperienceDetailItems(values.internships_items, 'internships'),
      projects: sanitizeExperienceDetailItems(values.projects_items, 'projects'),
      awards: sanitizeExperienceDetailItems(values.awards_items, 'awards'),
      open_source: sanitizeExperienceDetailItems(values.open_source_items, 'open_source'),
      leadership: sanitizeExperienceDetailItems(values.leadership_items, 'leadership')
    }
    return {
      name: studentName,
      mbti_type: values.mbti_type || null,
      hard_skills: normalizeHardSkillRows(values.hard_skills),
      soft_skills: values.soft_skills || [],
      certificates: values.certificates || [],
      experience: {
        internships: experienceDetailItems.internships.length,
        projects: experienceDetailItems.projects.length,
        awards: experienceDetailItems.awards.length,
        open_source: experienceDetailItems.open_source.length,
        leadership: experienceDetailItems.leadership.length
      },
      experience_detail_items: experienceDetailItems,
      experience_details: {
        internships: toEvidenceListFromItems(experienceDetailItems.internships, 'internships'),
        projects: toEvidenceListFromItems(experienceDetailItems.projects, 'projects'),
        awards: toEvidenceListFromItems(experienceDetailItems.awards, 'awards'),
        open_source: toEvidenceListFromItems(experienceDetailItems.open_source, 'open_source'),
        leadership: toEvidenceListFromItems(experienceDetailItems.leadership, 'leadership')
      },
      preferences: {
        preferred_locations: values.preferred_locations || [],
        preferred_job_families: preferredJobFamilies,
        target_salary_min: values.target_salary_min,
        target_salary_max: values.target_salary_max,
        notes: values.notes
      },
      raw_text: values.raw_text || '',
      resume_text: values.resume_text || ''
    }
  }

  const generateFromText = async () => {
    if (!canWrite) {
      message.warning('只读角色不可生成画像。')
      return
    }
    const text = form.getFieldValue('resume_text')
    if (!text) {
      message.warning('请先粘贴简历文本')
      return
    }
    setLoading(true)
    try {
      await api.post(`/students/${studentId}/profile/generate_from_text`, {
        ...buildProfileHintsForGenerate(),
        text
      })
      message.success('已从文本生成画像')
      await loadStudent(studentId)
    } finally {
      setLoading(false)
    }
  }

  const generateFromLatestResume = async () => {
    if (!canWrite) {
      message.warning('只读角色不可生成画像。')
      return
    }
    setLoading(true)
    try {
      await api.post(`/students/${studentId}/profile/generate_from_latest_resume`, buildProfileHintsForGenerate())
      message.success('已从最新简历生成画像')
      await loadStudent(studentId)
    } catch (e: any) {
      const detail = e?.response?.data?.detail
      const code = typeof detail === 'object' ? detail?.code : ''
      const msg = typeof detail === 'object' ? detail?.message : detail
      if (code === 'unsupported_resume_format') {
        message.error('仅支持常见简历文档文件')
      } else {
        message.error(msg || '简历解析失败')
      }
    } finally {
      setLoading(false)
    }
  }

  const openMbtiQuiz = async () => {
    if (!canWrite) {
      message.warning('只读角色不可提交测评。')
      return
    }
    if (!studentId) {
      message.warning('请先选择学生档案')
      return
    }
    setMbtiQuizLoading(true)
    try {
      const res = await api.get('/students/mbti/questions')
      const items = Array.isArray(res.data?.items) ? res.data.items as MBTIQuestionItem[] : []
      if (!items.length) {
        message.error('MBTI题库未加载成功')
        return
      }
      setMbtiQuestions(items)
      setMbtiAnswers({})
      setMbtiIndex(0)
      setMbtiQuizOpen(true)
    } catch {
      message.error('MBTI题库加载失败')
    } finally {
      setMbtiQuizLoading(false)
    }
  }

  const submitMbtiQuiz = async () => {
    if (!canWrite) {
      message.warning('只读角色不可提交测评。')
      return
    }
    if (!studentId || !mbtiQuestions.length) return

    const answers = mbtiQuestions.map((item) => String(mbtiAnswers[item.id] || '').trim().toUpperCase())
    const missingIndex = answers.findIndex((value) => !value)
    if (missingIndex >= 0) {
      message.warning(`第 ${missingIndex + 1} 题尚未作答`)
      setMbtiIndex(missingIndex)
      return
    }

    setMbtiQuizLoading(true)
    try {
      const res = await api.post(`/students/${studentId}/mbti/submit`, { answers })
      const mbtiType = String(res.data?.mbti_type || '').trim()
      if (mbtiType) {
        form.setFieldValue('mbti_type', mbtiType)
      }
      if (res.data?.profile) {
        setProfile(res.data.profile)
      }
      setMbtiQuizOpen(false)
      message.success(`MBTI测评完成：${mbtiType || '已回填'}`)
      await loadStudent(studentId)
    } catch (e: any) {
      const detail = e?.response?.data?.detail
      const msg = typeof detail === 'object' ? detail?.message : String(detail || '')
      message.error(msg || 'MBTI测评提交失败')
    } finally {
      setMbtiQuizLoading(false)
    }
  }

  const uploadProps: UploadProps = {
    multiple: false,
    maxCount: 1,
    disabled: !canWrite,
    customRequest: async (options) => {
      if (!canWrite) {
        options.onError?.(new Error('read_only'))
        return
      }
      try {
        const formData = new FormData()
        formData.append('file', options.file as File)
        await api.post(`/students/${studentId}/resume/upload`, formData, { headers: { 'Content-Type': 'multipart/form-data' } })
        message.success('简历上传成功')
        options.onSuccess?.({}, new XMLHttpRequest())
      } catch (error: any) {
        const detail = error?.response?.data?.detail
        const code = typeof detail === 'object' ? detail?.code : ''
        if (code === 'unsupported_resume_format') {
          message.error('仅支持常见简历文档文件')
        } else {
          message.error('简历上传失败')
        }
        options.onError?.(error as any)
      }
    }
  }

  const currentMbtiQuestion = mbtiQuestions[mbtiIndex]
  const currentMbtiAnswer = currentMbtiQuestion ? mbtiAnswers[currentMbtiQuestion.id] : undefined
  const answeredMbtiCount = Object.values(mbtiAnswers).filter((value) => String(value || '').trim()).length
  const mbtiProgressPercent = mbtiQuestions.length ? Math.round((answeredMbtiCount / mbtiQuestions.length) * 100) : 0
  const isLastMbtiQuestion = mbtiQuestions.length > 0 && mbtiIndex >= mbtiQuestions.length - 1

  return (
    <Space direction="vertical" style={{ width: '100%' }} size={16}>
      {!canWrite ? (
        <Alert type="info" showIcon message="当前账号为只读角色，页面可查看但不可上传/编辑/生成画像。" />
      ) : null}
      {personal ? <Alert type="info" showIcon message="这是你的个人画像空间。每个账号可建立一份画像，简历和规划报告仅供本人及管理人员访问。" /> : null}

      <Row gutter={[16, 16]}>
        <Col span={14}>
          <Card title={personal ? '我的信息与画像' : '学生信息与手动录入'}>
            <Space direction="vertical" size={16} style={{ width: '100%' }}>
              <Row gutter={[16, 16]}>
                <Col span={14}>
                  <Text type="secondary">{personal ? '我的档案' : '选择学生档案'}</Text>
                  <Select
                    style={{ width: '100%', marginTop: 8 }}
                    options={studentOptions}
                    value={studentId || undefined}
                    onChange={setStudentId}
                    showSearch
                    filterOption={false}
                    onSearch={(value) => { void loadStudents(String(value || '').trim()) }}
                  />
                </Col>
                <Col span={6}>
                  <Text type="secondary">姓名</Text>
                  <Input style={{ marginTop: 8 }} value={studentName} onChange={e => setStudentName(e.target.value)} disabled={!canWrite} />
                </Col>
                <Col span={4}>
                  <Text type="secondary">档案管理</Text>
                  <Button style={{ marginTop: 8, width: '100%' }} onClick={openCreateStudent} disabled={!canWrite || (personal && students.length > 0)}>{personal ? (students.length ? '画像已建立' : '建立画像') : '新增学生'}</Button>
                </Col>
              </Row>

              <Form form={form} layout="vertical" disabled={!canWrite}>
                <Form.Item label="MBTI（可选）" name="mbti_type">
                  <Select
                    allowClear
                    showSearch
                    options={MBTI_OPTIONS}
                    placeholder="例如 INTJ / ENFP"
                    optionFilterProp="label"
                  />
                </Form.Item>
                <Form.Item>
                  <Space wrap>
                    <Button
                      onClick={() => void openMbtiQuiz()}
                      loading={mbtiQuizLoading}
                      disabled={!canWrite || !studentId}
                    >
                      开始MBTI测评（自动填充）
                    </Button>
                    <Text type="secondary">完成测评后自动计算并回填学生画像 MBTI。</Text>
                  </Space>
                </Form.Item>
                <Form.Item label="硬技能与熟练度">
                  <Form.List name="hard_skills">
                    {(fields, { add, remove }) => (
                      <Space direction="vertical" size={8} style={{ width: '100%' }}>
                        {fields.map(({ key, name, ...restField }) => (
                          <Row key={key} gutter={8} align="middle">
                            <Col span={13}>
                              <Form.Item {...restField} name={[name, 'name']} rules={[{ required: true, message: '请填写技能' }]} style={{ marginBottom: 0 }}>
                                <Input placeholder="如 Java、Spring Boot、Redis" />
                              </Form.Item>
                            </Col>
                            <Col span={9}>
                              <Form.Item {...restField} name={[name, 'proficiency']} initialValue="delivery" style={{ marginBottom: 0 }}>
                                <Select options={PROFICIENCY_OPTIONS} />
                              </Form.Item>
                            </Col>
                            <Col span={2}>
                              <Button type="text" icon={<MinusCircleOutlined />} onClick={() => remove(name)} disabled={!canWrite} />
                            </Col>
                          </Row>
                        ))}
                        <Button type="dashed" icon={<PlusOutlined />} onClick={() => add({ name: '', proficiency: 'delivery' })} disabled={!canWrite}>
                          新增技能
                        </Button>
                      </Space>
                    )}
                  </Form.List>
                </Form.Item>
                <Form.Item label="软技能" name="soft_skills"><Select mode="tags" tokenSeparators={[',', '，']} placeholder="如 沟通协作、学习能力、创新能力" /></Form.Item>
                <Form.Item label="证书" name="certificates"><Select mode="tags" tokenSeparators={[',', '，']} placeholder="如 英语证书、软件水平考试、项目管理证书" /></Form.Item>

                <Row gutter={[16, 0]}>
                  <Col span={24}><Text type="secondary">计数字段由下方逐条经历自动计算，不再手动输入。</Text></Col>
                  <Col span={8}><Form.Item label="实习次数（自动）" name="internships"><InputNumber min={0} style={{ width: '100%' }} disabled /></Form.Item></Col>
                  <Col span={8}><Form.Item label="项目数量（自动）" name="projects"><InputNumber min={0} style={{ width: '100%' }} disabled /></Form.Item></Col>
                  <Col span={8}><Form.Item label="获奖数量（自动）" name="awards"><InputNumber min={0} style={{ width: '100%' }} disabled /></Form.Item></Col>
                  <Col span={12}><Form.Item label="开源经历（自动）" name="open_source"><InputNumber min={0} style={{ width: '100%' }} disabled /></Form.Item></Col>
                  <Col span={12}><Form.Item label="负责人经历（自动）" name="leadership"><InputNumber min={0} style={{ width: '100%' }} disabled /></Form.Item></Col>
                </Row>

                <Row gutter={[16, 0]}>
                  <Col span={24}>
                    <Text type="secondary">经历详情按完整经历维护：实习/项目左侧写总结概括，右侧写具体说明；获奖只写获得奖项。</Text>
                  </Col>
                  <Col span={24}>
                    <Form.Item label="实习详情（逐条编辑）">
                      <Form.List name="internships_items">
                        {(fields, { add, remove }) => (
                          <Space direction="vertical" size={8} style={{ width: '100%' }}>
                            {fields.map(({ key, name, ...restField }) => (
                              <Row key={key} gutter={8} align="middle">
                                <Col span={8}>
                                  <Form.Item {...restField} name={[name, 'content']} rules={[{ required: true, message: '请填写实习总结' }]} style={{ marginBottom: 0 }}>
                                    <Input placeholder="实习总结，如：百度后端开发实习生（2024.06-2024.10）" />
                                  </Form.Item>
                                </Col>
                                <Col span={15}>
                                  <Form.Item {...restField} name={[name, 'evidence']} rules={[{ required: true, message: '请填写具体实习内容' }]} style={{ marginBottom: 0 }}>
                                    <Input placeholder="具体做了什么，如：基于Spring Cloud+Redis开发订单流程，支撑日均5万+订单" />
                                  </Form.Item>
                                </Col>
                                <Col span={1}>
                                  <Button type="text" icon={<MinusCircleOutlined />} onClick={() => remove(name)} disabled={!canWrite} />
                                </Col>
                              </Row>
                            ))}
                            <Button type="dashed" icon={<PlusOutlined />} onClick={() => add({ content: '', evidence: '' })} disabled={!canWrite}>
                              新增实习条目
                            </Button>
                          </Space>
                        )}
                      </Form.List>
                    </Form.Item>
                  </Col>
                  <Col span={24}>
                    <Form.Item label="项目详情（逐条编辑）">
                      <Form.List name="projects_items">
                        {(fields, { add, remove }) => (
                          <Space direction="vertical" size={8} style={{ width: '100%' }}>
                            {fields.map(({ key, name, ...restField }) => (
                              <Row key={key} gutter={8} align="middle">
                                <Col span={8}>
                                  <Form.Item {...restField} name={[name, 'content']} rules={[{ required: true, message: '请填写项目总结' }]} style={{ marginBottom: 0 }}>
                                    <Input placeholder="项目总结，如：企业订单管理系统（实习项目）" />
                                  </Form.Item>
                                </Col>
                                <Col span={15}>
                                  <Form.Item {...restField} name={[name, 'evidence']} rules={[{ required: true, message: '请填写项目具体解释' }]} style={{ marginBottom: 0 }}>
                                    <Input placeholder="项目具体解释，如：使用RabbitMQ异步通知订单状态，查询效率提升65%" />
                                  </Form.Item>
                                </Col>
                                <Col span={1}>
                                  <Button type="text" icon={<MinusCircleOutlined />} onClick={() => remove(name)} disabled={!canWrite} />
                                </Col>
                              </Row>
                            ))}
                            <Button type="dashed" icon={<PlusOutlined />} onClick={() => add({ content: '', evidence: '' })} disabled={!canWrite}>
                              新增项目条目
                            </Button>
                          </Space>
                        )}
                      </Form.List>
                    </Form.Item>
                  </Col>
                  <Col span={24}>
                    <Form.Item label="获奖详情（逐条编辑）">
                      <Form.List name="awards_items">
                        {(fields, { add, remove }) => (
                          <Space direction="vertical" size={8} style={{ width: '100%' }}>
                            {fields.map(({ key, name, ...restField }) => (
                              <Row key={key} gutter={8} align="middle">
                                <Col span={23}>
                                  <Form.Item {...restField} name={[name, 'content']} rules={[{ required: true, message: '请填写获奖内容' }]} style={{ marginBottom: 0 }}>
                                    <Input placeholder="获得奖项，如：省级创新创业大赛一等奖" />
                                  </Form.Item>
                                </Col>
                                <Col span={1}>
                                  <Button type="text" icon={<MinusCircleOutlined />} onClick={() => remove(name)} disabled={!canWrite} />
                                </Col>
                              </Row>
                            ))}
                            <Button type="dashed" icon={<PlusOutlined />} onClick={() => add({ content: '', evidence: '' })} disabled={!canWrite}>
                              新增获奖条目
                            </Button>
                          </Space>
                        )}
                      </Form.List>
                    </Form.Item>
                  </Col>
                  <Col span={24}>
                    <Form.Item label="开源详情（逐条编辑）">
                      <Form.List name="open_source_items">
                        {(fields, { add, remove }) => (
                          <Space direction="vertical" size={8} style={{ width: '100%' }}>
                            {fields.map(({ key, name, ...restField }) => (
                              <Row key={key} gutter={8} align="middle">
                                <Col span={8}>
                                  <Form.Item {...restField} name={[name, 'content']} style={{ marginBottom: 0 }}>
                                    <Input placeholder="如：GitHub开源组件维护" />
                                  </Form.Item>
                                </Col>
                                <Col span={15}>
                                  <Form.Item {...restField} name={[name, 'evidence']} style={{ marginBottom: 0 }}>
                                    <Input placeholder="如：提交PR并被合入，累计200+Star" />
                                  </Form.Item>
                                </Col>
                                <Col span={1}>
                                  <Button type="text" icon={<MinusCircleOutlined />} onClick={() => remove(name)} disabled={!canWrite} />
                                </Col>
                              </Row>
                            ))}
                            <Button type="dashed" icon={<PlusOutlined />} onClick={() => add({ content: '', evidence: '' })} disabled={!canWrite}>
                              新增开源条目
                            </Button>
                          </Space>
                        )}
                      </Form.List>
                    </Form.Item>
                  </Col>
                  <Col span={24}>
                    <Form.Item label="负责人详情（逐条编辑）">
                      <Form.List name="leadership_items">
                        {(fields, { add, remove }) => (
                          <Space direction="vertical" size={8} style={{ width: '100%' }}>
                            {fields.map(({ key, name, ...restField }) => (
                              <Row key={key} gutter={8} align="middle">
                                <Col span={8}>
                                  <Form.Item {...restField} name={[name, 'content']} style={{ marginBottom: 0 }}>
                                    <Input placeholder="如：后端开发组长" />
                                  </Form.Item>
                                </Col>
                                <Col span={15}>
                                  <Form.Item {...restField} name={[name, 'evidence']} style={{ marginBottom: 0 }}>
                                    <Input placeholder="如：负责架构分工与接口评审，带领3人小组交付" />
                                  </Form.Item>
                                </Col>
                                <Col span={1}>
                                  <Button type="text" icon={<MinusCircleOutlined />} onClick={() => remove(name)} disabled={!canWrite} />
                                </Col>
                              </Row>
                            ))}
                            <Button type="dashed" icon={<PlusOutlined />} onClick={() => add({ content: '', evidence: '' })} disabled={!canWrite}>
                              新增负责人条目
                            </Button>
                          </Space>
                        )}
                      </Form.List>
                    </Form.Item>
                  </Col>
                </Row>

                <Row gutter={[16, 0]}>
                  <Col span={12}><Form.Item label="期望城市" name="preferred_locations"><Select mode="tags" tokenSeparators={[',', '，']} /></Form.Item></Col>
                  <Col span={12}><Form.Item label="期望方向" name="preferred_job_families"><Select mode="tags" options={familyChoiceOptions} tokenSeparators={[',', '，']} placeholder="可选预设方向，也可自定义输入" /></Form.Item></Col>
                  <Col span={12}><Form.Item label="期望最低月薪" name="target_salary_min"><InputNumber min={0} style={{ width: '100%' }} /></Form.Item></Col>
                  <Col span={12}><Form.Item label="期望最高月薪" name="target_salary_max"><InputNumber min={0} style={{ width: '100%' }} /></Form.Item></Col>
                </Row>

                <Form.Item label="补充说明（会参与手动画像完整度计算）" name="raw_text"><Input.TextArea rows={4} placeholder="可填学生特长、竞赛、社团、求职意愿等。" /></Form.Item>
                <Form.Item label="简历文本（用于自动解析）" name="resume_text"><Input.TextArea rows={6} placeholder="把简历文本直接贴进来，可快速生成画像。" /></Form.Item>
              </Form>

              <Space>
                <Button type="primary" loading={loading} onClick={() => void saveManualProfile()} disabled={!canWrite}>保存手动画像</Button>
                <Button loading={loading} onClick={() => void generateFromText()} disabled={!canWrite}>从文本生成画像</Button>
                <Button loading={loading} onClick={() => void generateFromLatestResume()} disabled={!canWrite}>从最新简历生成画像</Button>
              </Space>
            </Space>
          </Card>
        </Col>

        <Col span={10}>
          <Card title="简历上传与画像结果">
            <Space direction="vertical" size={16} style={{ width: '100%' }}>
              <Dragger {...uploadProps}>
                <p className="ant-upload-drag-icon"><InboxOutlined /></p>
                <p className="ant-upload-text">拖拽或点击上传简历文档</p>
                <p className="ant-upload-hint">上传后可点击“从最新简历生成画像”</p>
              </Dragger>

              <Row gutter={[12, 12]}>
                <Col span={12}><Card size="small"><Statistic title="完整度" value={profile?.completeness_score || 0} suffix="分" /></Card></Col>
                <Col span={12}><Card size="small"><Statistic title="竞争力" value={profile?.competitiveness_score || 0} suffix="分" /></Card></Col>
              </Row>

              <Progress percent={Math.round(profile?.completeness_score || 0)} status="active" />
              <Progress percent={Math.round(profile?.competitiveness_score || 0)} status="active" strokeColor="#52c41a" />

              <div>
                <Title level={5}>MBTI</Title>
                {profile?.mbti_type ? (
                  <Space direction="vertical" size={6}>
                    <Space wrap>
                      <Tag color="purple">{profile.mbti_type} {profile?.mbti_label ? `· ${profile.mbti_label}` : ''}</Tag>
                      {profile?.mbti_source ? <Tag>{SOURCE_LABELS[String(profile.mbti_source)] || String(profile.mbti_source)}</Tag> : null}
                    </Space>
                    {profile?.mbti_description ? (
                      <div>
                        <Text type="secondary">类型说明：</Text>
                        <div style={{ display: 'grid', gap: 6, marginTop: 6 }}>
                          {splitReadableLines(profile.mbti_description).map((item: string, idx: number) => (
                            <div
                              key={`mbti-desc-${idx}`}
                              style={{
                                padding: '6px 8px',
                                borderRadius: 8,
                                border: '1px solid #f0f0f0',
                                background: '#fafafa',
                                whiteSpace: 'normal',
                                wordBreak: 'break-word',
                                overflowWrap: 'anywhere',
                                lineHeight: 1.6
                              }}
                            >
                              • {item}
                            </div>
                          ))}
                        </div>
                      </div>
                    ) : null}
                    {(profile?.mbti_strengths || []).length ? (
                      <div>
                        <Text type="secondary">优势提示：</Text>
                        <div style={{ display: 'grid', gap: 6, marginTop: 6 }}>
                          {splitReadableCollection(profile?.mbti_strengths || []).map((item: string, idx: number) => (
                            <div
                              key={`mbti-strength-${idx}`}
                              style={{
                                padding: '6px 8px',
                                borderRadius: 8,
                                border: '1px solid #e6f4ff',
                                background: '#f6fbff',
                                whiteSpace: 'normal',
                                wordBreak: 'break-word',
                                overflowWrap: 'anywhere',
                                lineHeight: 1.6
                              }}
                            >
                              • {item}
                            </div>
                          ))}
                        </div>
                      </div>
                    ) : null}
                    {(profile?.mbti_challenges || []).length ? (
                      <div>
                        <Text type="secondary">潜在挑战：</Text>
                        <div style={{ display: 'grid', gap: 6, marginTop: 6 }}>
                          {splitReadableCollection(profile?.mbti_challenges || []).map((item: string, idx: number) => (
                            <div
                              key={`mbti-challenge-${idx}`}
                              style={{
                                padding: '6px 8px',
                                borderRadius: 8,
                                border: '1px solid #ffe7ba',
                                background: '#fff7e6',
                                whiteSpace: 'normal',
                                wordBreak: 'break-word',
                                overflowWrap: 'anywhere',
                                lineHeight: 1.6
                              }}
                            >
                              • {item}
                            </div>
                          ))}
                        </div>
                      </div>
                    ) : null}
                    {profile?.mbti_career_text ? (
                      <div>
                        <Text type="secondary">适合职业说明：</Text>
                        <div style={{ display: 'grid', gap: 6, marginTop: 6 }}>
                          {splitReadableLines(profile.mbti_career_text).map((item: string, idx: number) => (
                            <div
                              key={`mbti-career-${idx}`}
                              style={{
                                padding: '6px 8px',
                                borderRadius: 8,
                                border: '1px solid #f0f0f0',
                                background: '#fafafa',
                                whiteSpace: 'normal',
                                wordBreak: 'break-word',
                                overflowWrap: 'anywhere',
                                lineHeight: 1.6
                              }}
                            >
                              • {item}
                            </div>
                          ))}
                        </div>
                      </div>
                    ) : null}
                    {((profile?.preferences?.mbti_job_family_hint_labels || []).length || (profile?.mbti_job_family_hints || []).length) ? (
                      <div>
                        <Text type="secondary">适配职业方向：</Text>
                        <Space size={[0, 8]} wrap style={{ marginLeft: 8 }}>
                          {((profile?.preferences?.mbti_job_family_hint_labels || []).length
                            ? (profile?.preferences?.mbti_job_family_hint_labels || [])
                            : (profile?.mbti_job_family_hints || []).map((item: string) => familyLabel(item))
                          ).map((item: string) => <Tag color="blue" key={item}>{item}</Tag>)}
                        </Space>
                      </div>
                    ) : null}
                    {(profile?.mbti_career_keywords || []).length ? (
                      <div>
                        <Text type="secondary">职业关键词：</Text>
                        <div style={{ display: 'grid', gap: 6, marginTop: 6 }}>
                          {splitReadableCollection(profile?.mbti_career_keywords || []).map((item: string, idx: number) => (
                            <div
                              key={`mbti-keyword-${idx}`}
                              style={{
                                padding: '6px 8px',
                                borderRadius: 8,
                                border: '1px solid #d6e4ff',
                                background: '#f0f5ff',
                                whiteSpace: 'normal',
                                wordBreak: 'break-word',
                                overflowWrap: 'anywhere',
                                lineHeight: 1.6
                              }}
                            >
                              • {item}
                            </div>
                          ))}
                        </div>
                      </div>
                    ) : null}
                  </Space>
                ) : <Text type="secondary">未填写</Text>}
              </div>
              <div>
                <Title level={5}>硬技能</Title>
                <Space size={[0, 8]} wrap>{(profile?.hard_skills || []).map((item: any) => <Tag key={`${item.skill_id || ''}-${item.mention}`}>{item.mention}<span style={{ marginLeft: 6, opacity: 0.72 }}>{item.proficiency_label || proficiencyLabel(item.proficiency || item.level)}</span></Tag>)}</Space>
              </div>
              <div>
                <Title level={5}>软技能</Title>
                <Space size={[0, 8]} wrap>{(profile?.soft_skills || []).map((item: any) => <Tag color="blue" key={`${item.soft_skill_id || ''}-${item.name}`}>{item.name}</Tag>)}</Space>
              </div>
              <div>
                <Title level={5}>证书</Title>
                <Space size={[0, 8]} wrap>{(profile?.certificates || []).map((item: any) => <Tag color="gold" key={`${item.certificate_id || ''}-${item.name}`}>{item.name}</Tag>)}</Space>
              </div>

              <Card size="small" title="经历信号">
                <Row gutter={[8, 8]}>
                  <Col span={12}>
                    <Statistic title="实习" value={profile?.experience?.internships || 0} />
                    <Tag style={{ marginTop: 6 }}>{sourceTag('internships')}</Tag>
                  </Col>
                  <Col span={12}>
                    <Statistic title="项目" value={profile?.experience?.projects || 0} />
                    <Tag style={{ marginTop: 6 }}>{sourceTag('projects')}</Tag>
                  </Col>
                  <Col span={12}>
                    <Statistic title="开源" value={profile?.experience?.open_source || 0} />
                    <Tag style={{ marginTop: 6 }}>{sourceTag('open_source')}</Tag>
                  </Col>
                  <Col span={12}>
                    <Statistic title="负责人" value={profile?.experience?.leadership || 0} />
                    <Tag style={{ marginTop: 6 }}>{sourceTag('leadership')}</Tag>
                  </Col>
                </Row>
              </Card>

              <Card size="small" title="画像补充说明">
                <Space direction="vertical" size={10} style={{ width: '100%' }}>
                  <div>
                    <Text type="secondary">识别链路：</Text>
                    <Space wrap style={{ marginLeft: 8 }}>
                      <Tag color={extractionMeta?.llm_enabled ? 'blue' : 'default'}>{extractionMeta?.llm_enabled ? 'AI已启用' : 'AI未启用'}</Tag>
                      <Tag color={extractionMeta?.llm_profile_used ? 'green' : 'orange'}>{extractionMeta?.llm_profile_used ? '本次使用AI抽取' : '本次由规则兜底'}</Tag>
                    </Space>
                  </div>
                  <div>
                    <Text>{profile?.profile_notes || profile?.preferences?.notes || '暂无补充说明'}</Text>
                  </div>
                  <div>
                    <Text type="secondary">经历计数证据：</Text>
                    <div style={{ marginTop: 8 }}>
                      {['internships', 'projects', 'awards'].map((key) => {
                        const items = toExperienceDetailItems(detailItemsMap?.[key], evidenceMap?.[key], key)
                        const label = key === 'internships' ? '实习' : key === 'projects' ? '项目' : '获奖'
                        const detailLabel = key === 'internships' ? '具体实习内容' : key === 'projects' ? '项目具体解释' : ''
                        return (
                          <div key={key} style={{ marginBottom: 8 }}>
                            <Text strong>{label}</Text>
                            <div>
                              {items.length ? items.map((item: ExperienceDetailItem, idx: number) => (
                                <div
                                  key={`${key}-${idx}`}
                                  style={{
                                    marginTop: 6,
                                    padding: '6px 8px',
                                    borderRadius: 8,
                                    border: '1px solid #f0f0f0',
                                    background: '#fafafa',
                                    whiteSpace: 'pre-wrap',
                                    wordBreak: 'break-word',
                                    overflowWrap: 'anywhere',
                                  }}
                                >
                                  <div><Text strong>{String(item?.content || '-')}</Text></div>
                                  {key !== 'awards' ? (
                                    <div><Text type="secondary">{detailLabel}：{String(item?.evidence || '-')}</Text></div>
                                  ) : null}
                                </div>
                              )) : <Text type="secondary">无显式证据行</Text>}
                            </div>
                          </div>
                        )
                      })}
                    </div>
                  </div>
                </Space>
              </Card>

              <Card size="small" title="求职偏好">
                <Space direction="vertical" size={12} style={{ width: '100%' }}>
                  <div>
                    <Text strong>期望城市：</Text>
                    <Space size={[0, 8]} wrap style={{ marginLeft: 8 }}>
                      {(profile?.preferences?.preferred_locations || []).map((item: string) => <Tag key={item}>{item}</Tag>)}
                      {!(profile?.preferences?.preferred_locations || []).length ? <Text type="secondary">未填写</Text> : null}
                    </Space>
                  </div>
                  <div>
                    <Text strong>期望方向：</Text>
                    <Space size={[0, 8]} wrap style={{ marginLeft: 8 }}>
                      {(profile?.preferences?.preferred_job_families || []).map((item: string) => <Tag color="blue" key={item}>{familyLabel(item)}</Tag>)}
                      {!(profile?.preferences?.preferred_job_families || []).length ? <Text type="secondary">未填写</Text> : null}
                    </Space>
                  </div>
                </Space>
              </Card>

              <Card size="small" title="已有报告">
                <Space direction="vertical" style={{ width: '100%' }}>
                  {(reports || []).map((report: any) => (
                    <div key={report.report_id} style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <Text>{presentReportLabel(report, reports.indexOf(report))}</Text>
                      <Tag>{report.version}</Tag>
                    </div>
                  ))}
                  {!reports.length && <Text type="secondary">还没有生成报告。</Text>}
                </Space>
              </Card>
            </Space>
          </Card>
        </Col>
      </Row>

      <Modal
        title="MBTI 测评（自动填充学生画像）"
        open={mbtiQuizOpen}
        width={760}
        maskClosable={false}
        onCancel={() => setMbtiQuizOpen(false)}
        footer={[
          <Button key="cancel" onClick={() => setMbtiQuizOpen(false)} disabled={mbtiQuizLoading}>关闭</Button>,
          <Button
            key="prev"
            onClick={() => setMbtiIndex((prev) => Math.max(prev - 1, 0))}
            disabled={mbtiQuizLoading || mbtiIndex <= 0}
          >
            上一步
          </Button>,
          isLastMbtiQuestion ? (
            <Button key="submit" type="primary" loading={mbtiQuizLoading} onClick={() => void submitMbtiQuiz()}>
              提交并回填
            </Button>
          ) : (
            <Button
              key="next"
              type="primary"
              onClick={() => {
                if (!currentMbtiQuestion) return
                if (!String(currentMbtiAnswer || '').trim()) {
                  message.warning(`请先完成第 ${mbtiIndex + 1} 题`)
                  return
                }
                setMbtiIndex((prev) => Math.min(prev + 1, mbtiQuestions.length - 1))
              }}
              disabled={mbtiQuizLoading || !currentMbtiQuestion}
            >
              下一步
            </Button>
          ),
        ]}
      >
        <Space direction="vertical" size={14} style={{ width: '100%' }}>
          <Alert
            type="info"
            showIcon
            message={`步骤 ${Math.min(mbtiIndex + 1, mbtiQuestions.length || 1)}/${mbtiQuestions.length || 0}`}
            description="完成所有题目后，系统会自动计算 MBTI 并写入当前学生画像。"
          />
          <Progress percent={mbtiProgressPercent} />
          {currentMbtiQuestion ? (
            <Card size="small">
              <Space direction="vertical" style={{ width: '100%' }} size={12}>
                <Text strong>{currentMbtiQuestion.id}. {currentMbtiQuestion.question}</Text>
                <Radio.Group
                  value={currentMbtiAnswer}
                  onChange={(event) => {
                    const value = String(event.target.value || '').trim().toUpperCase()
                    setMbtiAnswers((prev) => ({ ...prev, [currentMbtiQuestion.id]: value }))
                  }}
                >
                  <Space direction="vertical">
                    <Radio value={currentMbtiQuestion.choice_a.value}>
                      {currentMbtiQuestion.choice_a.text}
                    </Radio>
                    <Radio value={currentMbtiQuestion.choice_b.value}>
                      {currentMbtiQuestion.choice_b.text}
                    </Radio>
                  </Space>
                </Radio.Group>
                <Text type="secondary">已完成 {answeredMbtiCount}/{mbtiQuestions.length} 题</Text>
              </Space>
            </Card>
          ) : (
            <Alert type="warning" showIcon message="题目加载中，请稍候重试。" />
          )}
        </Space>
      </Modal>

      <Modal
        title={personal ? '建立我的画像' : '新增学生档案'}
        open={createOpen}
        confirmLoading={creatingStudent}
        onOk={() => void createStudent()}
        onCancel={() => setCreateOpen(false)}
        okText="创建"
        cancelText="取消"
      >
        <Space direction="vertical" style={{ width: '100%' }}>
          <div>
            <Text type="secondary">姓名</Text>
            <Input value={newStudentName} onChange={(e) => setNewStudentName(e.target.value)} placeholder="默认使用当前时间" />
          </div>
        </Space>
      </Modal>
    </Space>
  )
}
