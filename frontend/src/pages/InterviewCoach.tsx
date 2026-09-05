import { personalStorageKey } from '../utils/personalStorage'
import React, { useEffect, useMemo, useRef, useState } from 'react'
import {
  AudioOutlined,
  CustomerServiceOutlined,
  PlayCircleOutlined,
  SendOutlined,
  StopOutlined
} from '@ant-design/icons'
import {
  Alert,
  App,
  Button,
  Card,
  Col,
  Empty,
  Input,
  List,
  Progress,
  Row,
  Select,
  Space,
  Statistic,
  Steps,
  Tag,
  Typography
} from 'antd'
import { api } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import FaceAuthPanel from '../components/FaceAuthPanel'
import { presentJobName, presentStudentOption } from '../utils/present'

const { Text, Title, Paragraph } = Typography
const LATEST_CODING_ASSESSMENT_KEY = 'interview.latestCodingAssessment'

type StudentItem = {
  student_id: string
  name?: string
}

type JobItem = {
  job_id: string
  title?: string
  description?: string
  company_name?: string
  location?: string
  overall_score?: number | null
  _source?: 'smart' | 'search'
}

type ReportItem = {
  report_id: string
  version?: number
  updated_at?: string
  created_at?: string
}

type InterviewQuestion = {
  question_id: string
  type?: string
  question: string
  focus?: string[]
}

type AnswerReview = {
  overall_score?: number
  dimension_scores?: Record<string, number>
  strengths?: string[]
  gaps?: string[]
  rewrite_suggestion?: string
  follow_up_question?: string
  report_note?: string
  llm_used?: boolean
}

type InterviewItem = {
  question: InterviewQuestion
  answer: string
  review?: AnswerReview
}

type InterviewSummary = {
  summary?: string
  overall_score?: number
  strengths?: string[]
  priority_gaps?: string[]
  action_items?: string[]
  report_markdown?: string
  llm_used?: boolean
}

type LinkedCodingAssessment = {
  student_id?: string
  job_id?: string
  updated_at?: string
  challenge?: {
    title?: string
    problem_id?: string
  }
  review?: {
    overall_score?: number
    interview_note?: string
  }
}

function readLatestCodingAssessment(studentId: string, jobId: string): LinkedCodingAssessment | null {
  if (typeof window === 'undefined' || !studentId) return null
  try {
    const raw = window.localStorage.getItem(personalStorageKey(LATEST_CODING_ASSESSMENT_KEY))
    if (!raw) return null
    const parsed = JSON.parse(raw) as LinkedCodingAssessment
    if (String(parsed?.student_id || '') !== String(studentId)) return null
    const linkedJobId = String(parsed?.job_id || '')
    if (jobId && linkedJobId && linkedJobId !== jobId) return null
    return parsed
  } catch {
    return null
  }
}

function scoreColor(score?: number) {
  const n = Number(score || 0)
  if (n >= 85) return '#52c41a'
  if (n >= 70) return '#1677ff'
  if (n >= 55) return '#faad14'
  return '#ff4d4f'
}

function mediaMimeType() {
  if (typeof MediaRecorder === 'undefined') return ''
  const candidates = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4']
  return candidates.find(type => MediaRecorder.isTypeSupported(type)) || ''
}

export default function InterviewCoach() {
  const { message } = App.useApp()
  const { canWrite } = useAuth()
  const [students, setStudents] = useState<StudentItem[]>([])
  const [jobs, setJobs] = useState<JobItem[]>([])
  const [reports, setReports] = useState<ReportItem[]>([])
  const [studentId, setStudentId] = useState('')
  const [jobId, setJobId] = useState('')
  const [jobSearchKeyword, setJobSearchKeyword] = useState('')
  const [jobLoading, setJobLoading] = useState(false)
  const [reportId, setReportId] = useState('')
  const [opening, setOpening] = useState('')
  const [coachHint, setCoachHint] = useState('')
  const [questions, setQuestions] = useState<InterviewQuestion[]>([])
  const [current, setCurrent] = useState(0)
  const [answerText, setAnswerText] = useState('')
  const [items, setItems] = useState<InterviewItem[]>([])
  const [summary, setSummary] = useState<InterviewSummary | null>(null)
  const [loadingStart, setLoadingStart] = useState(false)
  const [loadingReview, setLoadingReview] = useState(false)
  const [loadingSummary, setLoadingSummary] = useState(false)
  const [recording, setRecording] = useState(false)
  const [transcribing, setTranscribing] = useState(false)
  const [linkedCoding, setLinkedCoding] = useState<LinkedCodingAssessment | null>(null)
  const recorderRef = useRef<MediaRecorder | null>(null)
  const chunksRef = useRef<Blob[]>([])
  const streamRef = useRef<MediaStream | null>(null)
  const audioUrlRef = useRef<string | null>(null)
  const jobQuerySeqRef = useRef(0)

  const currentQuestion = current < questions.length ? questions[current] : undefined
  const answeredCount = items.filter(item => item.review).length

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
        const jobIdText = String(item.job_id || '').trim()
        const parts = [title]
        if (item._source === 'smart' && item.overall_score !== null && item.overall_score !== undefined) {
          parts.push(`匹配${Math.round(Number(item.overall_score || 0))}`)
        }
        if (company) parts.push(company)
        if (location) parts.push(location)
        if (jobIdText) parts.push(`ID:${jobIdText}`)
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

      return [{ label: '不指定岗位（按学生画像通用追问）', value: '' }, ...options]
    },
    [jobs]
  )

  const smartJobsCount = useMemo(
    () => jobs.filter(item => item._source === 'smart').length,
    [jobs]
  )

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
    return items.map(item => ({ ...item, _source: 'search' as const }))
  }

  const recommendJobs = async (sid: string, keyword: string = '') => {
    const student = String(sid || '').trim()
    if (!student) return []
    const res = await api.post('/match/recommend_jobs', {
      student_id: student,
      q: keyword || undefined,
      strategy: 'balanced',
      top_k: keyword ? 24 : 30,
      max_candidates: keyword ? 220 : 260,
      use_cache: true,
      ai_rerank_enabled: false,
      bge_rerank_enabled: false,
      semantic_enabled: false,
    })
    const items = (res.data?.items || []) as JobItem[]
    return items.map(item => ({ ...item, _source: 'smart' as const }))
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
      const [smartJobs, searchedJobs] = await Promise.all([
        shouldUseSmart ? recommendJobs(sid, q) : Promise.resolve([]),
        shouldUseSearch ? searchJobs(q) : Promise.resolve([])
      ])
      if (currentSeq !== jobQuerySeqRef.current) return
      setJobs(mergeCandidateJobs(smartJobs || [], searchedJobs || []))
    } catch {
      if (currentSeq !== jobQuerySeqRef.current) return
      setJobs([])
    } finally {
      if (currentSeq === jobQuerySeqRef.current) {
        setJobLoading(false)
      }
    }
  }

  const reportOptions = useMemo(
    () => reports.map(item => {
      const time = String(item.updated_at || item.created_at || '').replace('T', ' ').slice(0, 16)
      return {
        label: `${item.report_id}${item.version ? ` · v${item.version}` : ''}${time ? ` · ${time}` : ''}`,
        value: item.report_id
      }
    }),
    [reports]
  )

  const loadBase = async () => {
    const studentItems = await searchStudents()
    if (!studentId && studentItems.length) setStudentId(studentItems[0].student_id)
  }

  const loadReports = async (sid: string) => {
    const id = String(sid || '').trim()
    if (!id) {
      setReports([])
      setReportId('')
      return
    }
    const res = await api.get(`/students/${id}/reports`)
    const items = (res.data?.items || []) as ReportItem[]
    setReports(items)
    setReportId(prev => (prev && items.some(item => item.report_id === prev)) ? prev : (items[0]?.report_id || ''))
  }

  useEffect(() => {
    loadBase().catch(() => message.error('加载模拟面试基础数据失败'))
    return () => {
      if (audioUrlRef.current) URL.revokeObjectURL(audioUrlRef.current)
      streamRef.current?.getTracks().forEach(track => track.stop())
    }
  }, [])

  useEffect(() => {
    if (!studentId) return
    loadReports(studentId).catch(() => {
      setReports([])
      setReportId('')
    })
  }, [studentId])

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void loadJobCandidates(jobSearchKeyword)
    }, 320)
    return () => window.clearTimeout(timer)
  }, [studentId, jobSearchKeyword])

  useEffect(() => {
    setLinkedCoding(readLatestCodingAssessment(studentId, jobId))
  }, [studentId, jobId])

  const startSession = async () => {
    if (!studentId) {
      message.warning('请先选择学生')
      return
    }
    setLoadingStart(true)
    try {
      const res = await api.post('/interview/start', {
        student_id: studentId,
        job_id: jobId || undefined,
        question_count: 4
      })
      setOpening(String(res.data?.opening || ''))
      setCoachHint(String(res.data?.coach_hint || ''))
      setQuestions((res.data?.questions || []) as InterviewQuestion[])
      setCurrent(0)
      setAnswerText('')
      setItems([])
      setSummary(null)
      message.success('已生成岗位面试问题')
    } catch (e: any) {
      message.error(e?.response?.data?.detail?.message || '生成面试问题失败')
    } finally {
      setLoadingStart(false)
    }
  }

  const submitAnswer = async () => {
    if (!canWrite) {
      message.warning('只读角色不可提交模拟面试回答')
      return
    }
    if (!currentQuestion || !answerText.trim()) {
      message.warning('请先填写当前问题的回答')
      return
    }
    setLoadingReview(true)
    try {
      const history = items.map(item => ({
        question: item.question.question,
        answer: item.answer,
        review: item.review
      }))
      const res = await api.post('/interview/answer', {
        student_id: studentId,
        job_id: jobId || undefined,
        question: currentQuestion.question,
        answer: answerText,
        history
      })
      const review = res.data as AnswerReview
      const nextItems = [
        ...items,
        {
          question: currentQuestion,
          answer: answerText,
          review
        }
      ]
      setItems(nextItems)
      setAnswerText('')
      setCurrent(nextItems.length >= questions.length ? questions.length : current + 1)
      message.success('单题复盘完成')
    } catch (e: any) {
      message.error(e?.response?.data?.detail?.message || '点评失败')
    } finally {
      setLoadingReview(false)
    }
  }

  const finishSession = async () => {
    if (!items.length) {
      message.warning('至少完成一道面试题后再生成复盘')
      return
    }
    setLoadingSummary(true)
    try {
      const res = await api.post('/interview/summary', {
        student_id: studentId,
        job_id: jobId || undefined,
        items: items.map(item => ({
          question: item.question.question,
          answer: item.answer,
          review: item.review
        })),
        coding_review: linkedCoding?.review || undefined,
        coding_challenge: linkedCoding?.challenge || undefined
      })
      setSummary(res.data || null)
      message.success('面试总复盘已生成')
    } catch (e: any) {
      message.error(e?.response?.data?.detail?.message || '生成复盘失败')
    } finally {
      setLoadingSummary(false)
    }
  }

  const appendToReport = async () => {
    if (!canWrite) {
      message.warning('只读角色不可写入报告')
      return
    }
    if (!summary) {
      message.warning('请先生成总复盘')
      return
    }
    if (!reportId) {
      message.warning('当前学生暂无可写入的报告，请先在规划报告页生成报告')
      return
    }
    try {
      await api.post(`/reports/${reportId}/append_interview_summary`, summary)
      message.success('模拟面试复盘已写入职业规划报告')
      await loadReports(studentId)
    } catch (e: any) {
      message.error(e?.response?.data?.detail?.message || e?.response?.data?.error || '写入报告失败')
    }
  }

  const playText = async (text: string) => {
    const value = String(text || '').trim()
    if (!value) return
    try {
      const res = await api.post('/interview/speech/synthesize', { text: value }, { responseType: 'blob' })
      if (audioUrlRef.current) URL.revokeObjectURL(audioUrlRef.current)
      audioUrlRef.current = URL.createObjectURL(res.data)
      const audio = new Audio(audioUrlRef.current)
      await audio.play()
    } catch (e: any) {
      message.error('语音播报未完成，请重试')
    }
  }

  const startRecording = async () => {
    if (typeof navigator === 'undefined' || !navigator.mediaDevices?.getUserMedia) {
      message.warning('当前浏览器不支持录音')
      return
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      streamRef.current = stream
      chunksRef.current = []
      const mimeType = mediaMimeType()
      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined)
      recorderRef.current = recorder
      recorder.ondataavailable = event => {
        if (event.data?.size) chunksRef.current.push(event.data)
      }
      recorder.onstop = () => {
        stream.getTracks().forEach(track => track.stop())
        streamRef.current = null
        void transcribeRecordedAudio(mimeType)
      }
      recorder.start()
      setRecording(true)
    } catch {
      message.error('无法访问麦克风，请检查浏览器权限')
    }
  }

  const stopRecording = () => {
    recorderRef.current?.stop()
    recorderRef.current = null
    setRecording(false)
  }

  const transcribeRecordedAudio = async (mimeType: string) => {
    const chunks = chunksRef.current
    if (!chunks.length) return
    setTranscribing(true)
    try {
      const blob = new Blob(chunks, { type: mimeType || 'audio/webm' })
      const wavBlob = await convertAudioBlobToWav(blob)
      const form = new FormData()
      form.append('file', wavBlob, 'answer.wav')
      const res = await api.post('/interview/speech/transcribe', form, {
        headers: { 'Content-Type': 'multipart/form-data' }
      })
      const text = String(res.data?.text || '').trim()
      if (text) {
        setAnswerText(prev => [prev, text].filter(Boolean).join('\n'))
        message.success('语音已转写到回答框')
      } else {
        message.warning('语音转写结果为空')
      }
    } catch (e: any) {
      message.error('语音转写未完成，请重试')
    } finally {
      setTranscribing(false)
      chunksRef.current = []
    }
  }

  return (
    <Space direction="vertical" size={18} style={{ width: '100%' }}>
      {!canWrite ? (
        <Alert type="info" showIcon message="当前账号为只读角色，可查看模拟面试结果，但不可提交回答。" />
      ) : null}

      <Card title="岗位模拟面试控制台">
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
                onSearch={value => { void searchStudents(String(value || '').trim()) }}
              />
            </Col>
            <Col xs={24} md={10}>
              <Text type="secondary">目标岗位</Text>
              <Select
                style={{ width: '100%', marginTop: 6 }}
                value={jobId}
                onChange={setJobId}
                options={jobOptions}
                showSearch
                filterOption={false}
                loading={jobLoading}
                onSearch={value => { setJobSearchKeyword(String(value || '').trim()) }}
                notFoundContent={jobLoading ? '岗位搜索中...' : '暂无匹配岗位，可输入岗位ID/岗位名/公司/技能关键词'}
              />
              <div style={{ marginTop: 6 }}>
                <Text type="secondary">
                  {smartJobsCount > 0
                    ? `已按学生画像智能排序 ${smartJobsCount} 个岗位；输入关键词会检索数据库岗位并显示唯一岗位ID。`
                    : '输入岗位ID、岗位名、公司或技能关键词检索数据库岗位。'}
                </Text>
              </div>
            </Col>
            <Col xs={24} md={6}>
              <Text type="secondary">面试进度</Text>
              <div style={{ marginTop: 6 }}>
                <Progress percent={questions.length ? Math.round((answeredCount / questions.length) * 100) : 0} />
              </div>
            </Col>
          </Row>
          <Row gutter={[12, 12]}>
            <Col xs={24} md={12}>
              <Text type="secondary">写入目标报告</Text>
              <Select
                style={{ width: '100%', marginTop: 6 }}
                value={reportId}
                onChange={setReportId}
                options={reportOptions}
                placeholder="当前学生暂无报告"
                notFoundContent="当前学生暂无报告，请先生成职业规划报告"
              />
            </Col>
          </Row>
          <Space wrap>
            <Button type="primary" icon={<CustomerServiceOutlined />} loading={loadingStart} onClick={() => void startSession()}>
              生成岗位面试
            </Button>
            <Button loading={loadingSummary} onClick={() => void finishSession()} disabled={!items.length}>
              生成总复盘
            </Button>
            <Button onClick={() => void appendToReport()} disabled={!summary || !reportId || !canWrite}>
              写入规划报告
            </Button>
            <Button href="/interview/coding">
              进入代码能力评估
            </Button>
          </Space>
          {linkedCoding?.review ? (
            <Alert
              type="info"
              showIcon
              message="已关联最近一次代码能力评估"
              description={`当前将同步纳入 ${linkedCoding.challenge?.title || '代码能力评估'} 的结果，总分 ${linkedCoding.review?.overall_score || 0}。`}
            />
          ) : null}
          {opening ? <Alert type="success" showIcon message={opening} description={coachHint || undefined} /> : null}
        </Space>
      </Card>

      <FaceAuthPanel compact title="面试身份认证" />

      <Row gutter={[16, 16]}>
        <Col xs={24} xl={14}>
          <Card
            title="面试问答"
            extra={currentQuestion ? <Tag color="blue">第 {Math.min(current + 1, questions.length)} / {questions.length} 题</Tag> : null}
          >
            {currentQuestion ? (
              <Space direction="vertical" size={14} style={{ width: '100%' }}>
                <Steps
                  current={current}
                  size="small"
                  items={questions.map((q, idx) => ({ title: `Q${idx + 1}`, description: q.type || 'question' }))}
                />
                <div>
                  <Title level={4}>{currentQuestion.question}</Title>
                  <Space size={[0, 8]} wrap>
                    {(currentQuestion.focus || []).map(item => <Tag key={item}>{item}</Tag>)}
                  </Space>
                </div>
                <Space wrap>
                  <Button icon={<PlayCircleOutlined />} onClick={() => void playText(currentQuestion.question)}>
                    播放问题
                  </Button>
                  {!recording ? (
                    <Button icon={<AudioOutlined />} loading={transcribing} onClick={() => void startRecording()} disabled={!canWrite}>
                      录音回答
                    </Button>
                  ) : (
                    <Button danger icon={<StopOutlined />} onClick={stopRecording}>
                      停止录音
                    </Button>
                  )}
                </Space>
                <Input.TextArea
                  rows={8}
                  value={answerText}
                  onChange={event => setAnswerText(event.target.value)}
                  placeholder="可以直接输入回答，也可以录音后自动转写到这里。建议按 STAR：背景、任务、行动、结果。"
                />
                <Button
                  type="primary"
                  icon={<SendOutlined />}
                  loading={loadingReview}
                  onClick={() => void submitAnswer()}
                  disabled={!canWrite}
                >
                  提交并点评
                </Button>
              </Space>
            ) : (
              <Empty description={questions.length ? '本轮问题已答完，请生成总复盘' : '先生成岗位面试问题'} />
            )}
          </Card>
        </Col>

        <Col xs={24} xl={10}>
          <Card title="单题复盘">
            {items.length ? (
              <List
                itemLayout="vertical"
                dataSource={items}
                renderItem={(item, index) => (
                  <List.Item>
                    <Space direction="vertical" size={10} style={{ width: '100%' }}>
                      <Space wrap>
                        <Tag color="geekblue">Q{index + 1}</Tag>
                        <Tag color="green">智能点评</Tag>
                      </Space>
                      <Text strong>{item.question.question}</Text>
                      <Paragraph type="secondary" ellipsis={{ rows: 2, expandable: true }}>
                        {item.answer}
                      </Paragraph>
                      <Progress
                        percent={Math.round(Number(item.review?.overall_score || 0))}
                        strokeColor={scoreColor(item.review?.overall_score)}
                      />
                      <div>
                        <Text strong>优势：</Text>
                        <Text>{(item.review?.strengths || []).join('；') || '暂无'}</Text>
                      </div>
                      <div>
                        <Text strong>改进：</Text>
                        <Text>{(item.review?.gaps || []).join('；') || '暂无'}</Text>
                      </div>
                      {item.review?.rewrite_suggestion ? (
                        <Alert type="info" message="表达优化建议" description={item.review.rewrite_suggestion} />
                      ) : null}
                    </Space>
                  </List.Item>
                )}
              />
            ) : (
              <Empty description="提交回答后展示单题评分和追问建议" />
            )}
          </Card>
        </Col>
      </Row>

      <Card title="总复盘与报告素材">
        {summary ? (
          <Space direction="vertical" size={14} style={{ width: '100%' }}>
            <Row gutter={[12, 12]}>
              <Col xs={24} md={8}>
                <Card size="small">
                  <Statistic title="总分" value={summary.overall_score || 0} />
                </Card>
              </Col>
              <Col xs={24} md={8}>
                <Card size="small">
                  <Statistic title="完成题数" value={items.length} />
                </Card>
              </Col>
              <Col xs={24} md={8}>
                <Card size="small">
                  <Statistic title="复盘方式" value="智能复盘" />
                </Card>
              </Col>
            </Row>
            <Alert type="success" showIcon message={summary.summary || '已生成复盘'} />
            <Row gutter={[12, 12]}>
              <Col xs={24} md={8}>
                <Title level={5}>优势</Title>
                <List size="small" dataSource={summary.strengths || []} renderItem={item => <List.Item>{item}</List.Item>} />
              </Col>
              <Col xs={24} md={8}>
                <Title level={5}>优先短板</Title>
                <List size="small" dataSource={summary.priority_gaps || []} renderItem={item => <List.Item>{item}</List.Item>} />
              </Col>
              <Col xs={24} md={8}>
                <Title level={5}>行动项</Title>
                <List size="small" dataSource={summary.action_items || []} renderItem={item => <List.Item>{item}</List.Item>} />
              </Col>
            </Row>
            <div>
              <Title level={5}>可写入报告的 Markdown</Title>
              <Input.TextArea rows={8} value={summary.report_markdown || ''} readOnly />
            </div>
          </Space>
        ) : (
          <Empty description="完成面试后点击“生成总复盘”" />
        )}
      </Card>
    </Space>
  )
}

async function convertAudioBlobToWav(blob: Blob): Promise<Blob> {
  const AudioContextClass = window.AudioContext || (window as any).webkitAudioContext
  if (!AudioContextClass) return blob
  const buffer = await blob.arrayBuffer()
  const context = new AudioContextClass()
  try {
    const audioBuffer = await context.decodeAudioData(buffer.slice(0))
    const wavBuffer = encodeWav(audioBuffer)
    return new Blob([wavBuffer], { type: 'audio/wav' })
  } finally {
    await context.close?.()
  }
}

function encodeWav(audioBuffer: AudioBuffer): ArrayBuffer {
  const channels = Math.min(1, audioBuffer.numberOfChannels)
  const sampleRate = audioBuffer.sampleRate
  const samples = audioBuffer.getChannelData(0)
  const bytesPerSample = 2
  const blockAlign = channels * bytesPerSample
  const buffer = new ArrayBuffer(44 + samples.length * bytesPerSample)
  const view = new DataView(buffer)

  writeString(view, 0, 'RIFF')
  view.setUint32(4, 36 + samples.length * bytesPerSample, true)
  writeString(view, 8, 'WAVE')
  writeString(view, 12, 'fmt ')
  view.setUint32(16, 16, true)
  view.setUint16(20, 1, true)
  view.setUint16(22, channels, true)
  view.setUint32(24, sampleRate, true)
  view.setUint32(28, sampleRate * blockAlign, true)
  view.setUint16(32, blockAlign, true)
  view.setUint16(34, 16, true)
  writeString(view, 36, 'data')
  view.setUint32(40, samples.length * bytesPerSample, true)

  let offset = 44
  for (let i = 0; i < samples.length; i += 1) {
    const s = Math.max(-1, Math.min(1, samples[i]))
    view.setInt16(offset, s < 0 ? s * 0x8000 : s * 0x7fff, true)
    offset += 2
  }
  return buffer
}

function writeString(view: DataView, offset: number, value: string) {
  for (let i = 0; i < value.length; i += 1) {
    view.setUint8(offset + i, value.charCodeAt(i))
  }
}
