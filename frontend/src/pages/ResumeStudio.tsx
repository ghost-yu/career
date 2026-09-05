import React, { useEffect, useMemo, useRef, useState } from 'react'
import { ExportOutlined } from '@ant-design/icons'
import {
  Alert,
  App,
  Button,
  Card,
  Col,
  Divider,
  Empty,
  Grid,
  Input,
  Row,
  Select,
  Space,
  Statistic,
  Switch,
  Tag,
  Typography
} from 'antd'
import { api } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { presentJobName, presentStudentOption } from '../utils/present'
import { saveResumeTemplateDraft } from '../utils/resumeTemplateDraft'

const { Text, Title } = Typography

type StudentItem = {
  student_id: string
  name?: string
}

type JobItem = {
  job_id: string
  title?: string
  description?: string
  location?: string
  company_name?: string
  overall_score?: number | null
  _source?: 'smart' | 'search'
}

type ResumeGenerateResult = {
  ok?: boolean
  student_id?: string
  source_filename?: string | null
  target_job_id?: string | null
  llm_used?: boolean
  resume_markdown?: string
  targeted_summary?: string
  highlighted_keywords?: string[]
  missing_keywords?: string[]
  risk_notes?: string[]
  cover_letter?: string
}

type FitScoreResult = {
  ok?: boolean
  student_id?: string | null
  job_id?: string | null
  job_title?: string
  base_score_100?: number | null
  llm_used?: boolean
  fit_score_10?: number
  fit_label?: string
  confidence?: number
  matched_keywords?: string[]
  missing_keywords?: string[]
  reasoning?: string
  next_actions?: string[]
  error?: string
}

function fitLabelText(value?: string) {
  const key = String(value || '').trim().toLowerCase()
  if (key === 'strong') return '强匹配'
  if (key === 'good') return '较好匹配'
  if (key === 'moderate') return '中等匹配'
  if (key === 'weak') return '弱匹配'
  if (key === 'poor') return '低匹配'
  return '未评估'
}

function fitTagColor(score10?: number) {
  const n = Number(score10 || 0)
  if (n >= 8) return 'green'
  if (n >= 6) return 'blue'
  if (n >= 4) return 'orange'
  return 'red'
}

export default function ResumeStudio() {
  const { message } = App.useApp()
  const { canWrite } = useAuth()
  const screens = Grid.useBreakpoint()

  const [students, setStudents] = useState<StudentItem[]>([])
  const [jobs, setJobs] = useState<JobItem[]>([])
  const [studentId, setStudentId] = useState('')
  const [jobId, setJobId] = useState('')
  const [jobSearchKeyword, setJobSearchKeyword] = useState('')
  const [jobLoading, setJobLoading] = useState(false)
  const [targetTitle, setTargetTitle] = useState('')
  const [jobDescription, setJobDescription] = useState('')
  const [resumeText, setResumeText] = useState('')
  const [includeCoverLetter, setIncludeCoverLetter] = useState(false)
  const [resumeResult, setResumeResult] = useState<ResumeGenerateResult | null>(null)
  const [scoreResult, setScoreResult] = useState<FitScoreResult | null>(null)
  const [loadingGenerate, setLoadingGenerate] = useState(false)
  const [loadingScore, setLoadingScore] = useState(false)
  const jobQuerySeqRef = useRef(0)

  const searchStudents = async (keyword: string = '') => {
    const res = await api.get('/students', {
      params: { limit: 200, offset: 0, q: keyword || undefined }
    })
    const items = (res.data?.items || []) as StudentItem[]
    setStudents(items)
    return items
  }

  const searchJobs = async (keyword: string = '') => {
    const res = await api.get('/jobs', {
      params: { limit: keyword ? 120 : 80, offset: 0, q: keyword || undefined }
    })
    const items = (res.data?.items || []) as JobItem[]
    return items.map((item) => ({ ...item, _source: 'search' as const }))
  }

  const recommendJobs = async (sid: string, keyword: string = '') => {
    const student = String(sid || '').trim()
    if (!student) return []
    const body = {
      student_id: student,
      q: keyword || undefined,
      strategy: 'balanced',
      top_k: keyword ? 24 : 30,
      max_candidates: keyword ? 220 : 260,
      use_cache: true,
      ai_rerank_enabled: false,
      bge_rerank_enabled: false,
      semantic_enabled: false,
    }
    const res = await api.post('/match/recommend_jobs', body)
    const items = (res.data?.items || []) as JobItem[]
    return items.map((item) => ({ ...item, _source: 'smart' as const }))
  }

  const mergeCandidateJobs = (smartJobs: JobItem[], searchedJobs: JobItem[]) => {
    const merged: JobItem[] = []
    const byId = new Map<string, number>()

    for (const row of [...smartJobs, ...searchedJobs]) {
      const id = String(row?.job_id || '').trim()
      if (!id) continue
      if (!byId.has(id)) {
        byId.set(id, merged.length)
        merged.push(row)
        continue
      }
      const prevIndex = byId.get(id)
      if (prevIndex === undefined) continue
      const prev = merged[prevIndex]
      if (prev?._source === 'smart') continue
      merged[prevIndex] = { ...row, _source: prev?._source || row?._source }
    }
    return merged
  }

  const loadJobCandidates = async (keyword: string = '') => {
    const q = String(keyword || '').trim()
    const currentSeq = ++jobQuerySeqRef.current
    setJobLoading(true)
    try {
      const sid = String(studentId || '').trim()
      const shouldUseSmart = false
      const shouldUseSearch = q.length >= 2 || !sid

      const tasks: Array<Promise<JobItem[]>> = []
      if (shouldUseSmart) {
        tasks.push(recommendJobs(sid, q))
      }
      if (shouldUseSearch) {
        tasks.push(searchJobs(q))
      }

      const [smartJobs, searchedJobs] = await Promise.all([
        shouldUseSmart ? tasks[0] : Promise.resolve([]),
        shouldUseSearch ? tasks[shouldUseSmart ? 1 : 0] : Promise.resolve([])
      ])

      if (currentSeq !== jobQuerySeqRef.current) return
      const merged = mergeCandidateJobs(smartJobs || [], searchedJobs || [])
      setJobs(merged)
    } catch {
      if (currentSeq !== jobQuerySeqRef.current) return
      setJobs([])
    } finally {
      if (currentSeq === jobQuerySeqRef.current) {
        setJobLoading(false)
      }
    }
  }

  const loadBase = async () => {
    const [studentItems] = await Promise.all([searchStudents()])
    if (!studentId && studentItems.length) {
      setStudentId(studentItems[0].student_id)
    }
  }

  useEffect(() => {
    loadBase().catch(() => message.error('加载 AI简历 数据失败'))
  }, [])

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void loadJobCandidates(jobSearchKeyword)
    }, 320)
    return () => window.clearTimeout(timer)
  }, [studentId, jobSearchKeyword])

  const selectedJob = useMemo(
    () => jobs.find(item => item.job_id === jobId),
    [jobs, jobId]
  )

  useEffect(() => {
    if (!selectedJob) return
    if (!targetTitle) {
      setTargetTitle(String(selectedJob.title || ''))
    }
    if (!jobDescription) {
      setJobDescription(String(selectedJob.description || ''))
    }
  }, [selectedJob])

  const studentOptions = useMemo(
    () => students.map((item, index) => ({ label: presentStudentOption(item, index), value: item.student_id })),
    [students]
  )

  const jobOptions = useMemo(
    () => {
      const baseLabelMap = new Map<string, number>()
      const baseLabels = jobs.map((item, index) => {
        const title = presentJobName(item, index)
        const company = String(item.company_name || '').trim()
        const location = String(item.location || '').trim()
        const parts = [title]
        if (item._source === 'smart' && item.overall_score !== null && item.overall_score !== undefined) {
          parts.push(`匹配${Math.round(Number(item.overall_score || 0))}`)
        }
        if (company) parts.push(company)
        if (location) parts.push(location)
        const base = parts.join(' · ')
        baseLabelMap.set(base, (baseLabelMap.get(base) || 0) + 1)
        return base
      })

      const seen = new Map<string, number>()
      const options = jobs.map((item, index) => {
        const base = baseLabels[index]
        const total = baseLabelMap.get(base) || 1
        const current = (seen.get(base) || 0) + 1
        seen.set(base, current)
        const label = total > 1 ? `${base} · 样本${current}` : base
        return { label, value: item.job_id }
      })

      return [{ label: '不指定岗位（仅按输入描述）', value: '' }, ...options]
    },
    [jobs]
  )

  const smartJobsCount = useMemo(
    () => jobs.filter((item) => item._source === 'smart').length,
    [jobs]
  )

  const runGenerateResume = async () => {
    if (!canWrite) {
      message.warning('只读角色不可执行 AI 写简历')
      return
    }
    if (!studentId) {
      message.warning('请先选择学生')
      return
    }
    setLoadingGenerate(true)
    try {
      const body = {
        job_id: jobId || undefined,
        target_title: targetTitle || undefined,
        job_description: jobDescription || undefined,
        resume_text: resumeText || undefined,
        include_cover_letter: includeCoverLetter
      }
      const res = await api.post(`/students/${studentId}/resume/ai_generate`, body)
      setResumeResult(res.data || null)
      message.success('AI简历生成完成')
    } catch (e: any) {
      const detail = e?.response?.data?.detail
      const msg = typeof detail === 'object' ? detail?.message : detail
      message.error(msg || 'AI简历生成失败')
    } finally {
      setLoadingGenerate(false)
    }
  }

  const runFitScore = async () => {
    if (!canWrite) {
      message.warning('只读角色不可执行 AI 打分')
      return
    }
    if (!studentId) {
      message.warning('请先选择学生')
      return
    }
    setLoadingScore(true)
    try {
      const body = {
        student_id: studentId,
        job_id: jobId || undefined,
        job_title: targetTitle || undefined,
        job_description: jobDescription || undefined,
        resume_text: resumeText || undefined,
        use_cache: true
      }
      const res = await api.post('/match/score_fit_ai', body)
      const data = (res.data || {}) as FitScoreResult
      if (data.error) {
        message.error(data.error)
      }
      setScoreResult(data)
      if (!data.error) {
        message.success('AI打分完成')
      }
    } catch (e: any) {
      message.error(e?.response?.data?.detail || 'AI打分失败')
    } finally {
      setLoadingScore(false)
    }
  }

  const openTemplateEditor = () => {
    if (!resumeResult) {
      message.warning('请先生成简历后再打开模板编辑器')
      return
    }
    const draftKey = saveResumeTemplateDraft({
      student_id: resumeResult.student_id || studentId || undefined,
      job_id: resumeResult.target_job_id || jobId || undefined,
      target_title: targetTitle || undefined,
      source_filename: resumeResult.source_filename || undefined,
      llm_used: resumeResult.llm_used,
      generated_at: new Date().toISOString(),
      resume_markdown: String(resumeResult.resume_markdown || ''),
      targeted_summary: String(resumeResult.targeted_summary || ''),
      highlighted_keywords: resumeResult.highlighted_keywords || [],
      missing_keywords: resumeResult.missing_keywords || [],
      risk_notes: resumeResult.risk_notes || [],
      cover_letter: String(resumeResult.cover_letter || '')
    })
    const popup = window.open(
      `/resume/editor?draft=${encodeURIComponent(draftKey)}`,
      '_blank',
      'noopener,noreferrer,width=1500,height=960'
    )
    if (!popup) {
      message.warning('浏览器拦截了弹窗，请允许弹窗后重试')
    }
  }

  return (
    <Space direction="vertical" size={18} style={{ width: '100%' }}>
      {!canWrite ? (
        <Alert
          type="info"
          showIcon
          message="当前账号为只读角色，可查看结果但不可执行 AI 写简历与 AI 打分。"
        />
      ) : null}

      <Card title="AI简历控制台">
        <Space direction="vertical" size={14} style={{ width: '100%' }}>
          <Row gutter={[12, 12]}>
            <Col xs={24} md={8}>
              <Text type="secondary">学生</Text>
              <Select
                style={{ width: '100%', marginTop: 6 }}
                value={studentId}
                onChange={setStudentId}
                options={studentOptions}
                showSearch
                filterOption={false}
                onSearch={(value) => { void searchStudents(String(value || '').trim()) }}
              />
            </Col>
            <Col xs={24} md={10}>
              <Text type="secondary">岗位</Text>
              <Select
                style={{ width: '100%', marginTop: 6 }}
                value={jobId}
                onChange={setJobId}
                options={jobOptions}
                showSearch
                filterOption={false}
                loading={jobLoading}
                onSearch={(value) => { setJobSearchKeyword(String(value || '').trim()) }}
                notFoundContent={jobLoading ? '岗位搜索中...' : '暂无匹配岗位，可尝试输入岗位名/技能关键词'}
              />
              <div style={{ marginTop: 6 }}>
                <Text type="secondary">
                  {smartJobsCount > 0
                    ? `已按学生画像智能排序 ${smartJobsCount} 个岗位；输入关键词可检索全量岗位并自动融合。`
                    : '当前展示为关键词检索结果。建议先选择学生以启用智能匹配排序。'}
                </Text>
              </div>
            </Col>
            <Col xs={24} md={6}>
              <Text type="secondary">附带求职信</Text>
              <div style={{ marginTop: 10 }}>
                <Switch checked={includeCoverLetter} onChange={setIncludeCoverLetter} />
              </div>
            </Col>
          </Row>

          <Row gutter={[12, 12]}>
            <Col xs={24} md={12}>
              <Text type="secondary">目标岗位标题（可覆盖）</Text>
              <Input
                style={{ marginTop: 6 }}
                value={targetTitle}
                onChange={e => setTargetTitle(e.target.value)}
                placeholder="如：后端开发工程师"
              />
            </Col>
            <Col xs={24} md={12}>
              <Text type="secondary">岗位描述（可覆盖）</Text>
              <Input.TextArea
                style={{ marginTop: 6 }}
                rows={3}
                value={jobDescription}
                onChange={e => setJobDescription(e.target.value)}
                placeholder="粘贴岗位 JD 文本"
              />
            </Col>
          </Row>

          <div>
            <Text type="secondary">手动简历文本（可选，留空则使用学生最新上传的 PDF/DOCX）</Text>
            <Input.TextArea
              style={{ marginTop: 6 }}
              rows={screens.md ? 6 : 4}
              value={resumeText}
              onChange={e => setResumeText(e.target.value)}
              placeholder="用于测试时可直接粘贴简历正文"
            />
          </div>

          <Space wrap>
            <Button type="primary" loading={loadingGenerate} onClick={() => void runGenerateResume()} disabled={!canWrite}>
              AI写简历
            </Button>
            <Button loading={loadingScore} onClick={() => void runFitScore()} disabled={!canWrite}>
              AI适配打分
            </Button>
          </Space>
        </Space>
      </Card>

      <Row gutter={[16, 16]}>
        <Col xs={24} xl={14}>
          <Card title="AI 简历结果">
            {resumeResult ? (
              <Space direction="vertical" size={14} style={{ width: '100%' }}>
                <Row gutter={[12, 12]}>
                  <Col xs={24} md={8}>
                    <Card size="small">
                      <Statistic title="LLM链路" value={resumeResult.llm_used ? '已调用' : '未调用'} />
                    </Card>
                  </Col>
                  <Col xs={24} md={8}>
                    <Card size="small">
                      <Statistic title="来源文件" value={resumeResult.source_filename || '-'} />
                    </Card>
                  </Col>
                  <Col xs={24} md={8}>
                    <Card size="small">
                      <Statistic title="目标岗位ID" value={resumeResult.target_job_id || '-'} />
                    </Card>
                  </Col>
                </Row>

                <Space wrap>
                  <Button icon={<ExportOutlined />} onClick={openTemplateEditor}>
                    弹出模板编辑器（新页面）
                  </Button>
                </Space>

                <div>
                  <Title level={5}>定向摘要</Title>
                  <Text>{resumeResult.targeted_summary || '暂无'}</Text>
                </div>

                <div>
                  <Title level={5}>命中关键词</Title>
                  <Space size={[0, 8]} wrap>
                    {(resumeResult.highlighted_keywords || []).map(value => (
                      <Tag color="green" key={value}>{value}</Tag>
                    ))}
                    {!resumeResult.highlighted_keywords?.length ? <Text type="secondary">暂无</Text> : null}
                  </Space>
                </div>

                <div>
                  <Title level={5}>缺口关键词</Title>
                  <Space size={[0, 8]} wrap>
                    {(resumeResult.missing_keywords || []).map(value => (
                      <Tag color="orange" key={value}>{value}</Tag>
                    ))}
                    {!resumeResult.missing_keywords?.length ? <Text type="secondary">暂无</Text> : null}
                  </Space>
                </div>

                <div>
                  <Title level={5}>风险提示</Title>
                  <Space direction="vertical" size={6} style={{ width: '100%' }}>
                    {(resumeResult.risk_notes || []).map(value => (
                      <Text key={value}>- {value}</Text>
                    ))}
                    {!resumeResult.risk_notes?.length ? <Text type="secondary">暂无</Text> : null}
                  </Space>
                </div>

                <Divider style={{ margin: '4px 0' }} />

                <div>
                  <Title level={5}>简历 Markdown</Title>
                  <Input.TextArea
                    rows={screens.md ? 18 : 12}
                    value={resumeResult.resume_markdown || ''}
                    readOnly
                  />
                </div>

                <div>
                  <Title level={5}>求职信</Title>
                  <Input.TextArea
                    rows={screens.md ? 7 : 5}
                    value={resumeResult.cover_letter || ''}
                    readOnly
                  />
                </div>
              </Space>
            ) : (
              <Empty description="点击“AI写简历”后查看结果" />
            )}
          </Card>
        </Col>

        <Col xs={24} xl={10}>
          <Card title="AI 适配打分">
            {scoreResult ? (
              <Space direction="vertical" size={14} style={{ width: '100%' }}>
                {scoreResult.error ? (
                  <Alert type="error" showIcon message={scoreResult.error} />
                ) : (
                  <>
                    <Row gutter={[12, 12]}>
                      <Col xs={24} sm={12}>
                        <Card size="small">
                          <Statistic title="匹配分(1-10)" value={scoreResult.fit_score_10 || 0} />
                        </Card>
                      </Col>
                      <Col xs={24} sm={12}>
                        <Card size="small">
                          <Statistic
                            title="基础分(100制)"
                            value={scoreResult.base_score_100 ?? '-'}
                          />
                        </Card>
                      </Col>
                      <Col xs={24} sm={12}>
                        <Card size="small">
                          <Statistic title="置信度" value={Math.round(Number(scoreResult.confidence || 0) * 100)} suffix="%" />
                        </Card>
                      </Col>
                      <Col xs={24} sm={12}>
                        <Card size="small">
                          <Statistic title="LLM链路" value={scoreResult.llm_used ? '已调用' : '未调用'} />
                        </Card>
                      </Col>
                    </Row>

                    <div>
                      <Title level={5}>匹配等级</Title>
                      <Tag color={fitTagColor(scoreResult.fit_score_10)}>{fitLabelText(scoreResult.fit_label)}</Tag>
                    </div>

                    <div>
                      <Title level={5}>命中关键词</Title>
                      <Space size={[0, 8]} wrap>
                        {(scoreResult.matched_keywords || []).map(value => (
                          <Tag color="green" key={value}>{value}</Tag>
                        ))}
                        {!scoreResult.matched_keywords?.length ? <Text type="secondary">暂无</Text> : null}
                      </Space>
                    </div>

                    <div>
                      <Title level={5}>缺口关键词</Title>
                      <Space size={[0, 8]} wrap>
                        {(scoreResult.missing_keywords || []).map(value => (
                          <Tag color="orange" key={value}>{value}</Tag>
                        ))}
                        {!scoreResult.missing_keywords?.length ? <Text type="secondary">暂无</Text> : null}
                      </Space>
                    </div>

                    <div>
                      <Title level={5}>评分解释</Title>
                      <Text>{scoreResult.reasoning || '暂无'}</Text>
                    </div>

                    <div>
                      <Title level={5}>下一步建议</Title>
                      <Space direction="vertical" size={6} style={{ width: '100%' }}>
                        {(scoreResult.next_actions || []).map(value => (
                          <Text key={value}>- {value}</Text>
                        ))}
                        {!scoreResult.next_actions?.length ? <Text type="secondary">暂无</Text> : null}
                      </Space>
                    </div>
                  </>
                )}
              </Space>
            ) : (
              <Empty description="点击“AI适配打分”后查看结果" />
            )}
          </Card>
        </Col>
      </Row>
    </Space>
  )
}
