import { personalStorageKey } from '../utils/personalStorage'
import React, { useEffect, useMemo, useRef, useState } from 'react'
import {
  Alert,
  App,
  Button,
  Card,
  Col,
  Divider,
  Empty,
  List,
  Progress,
  Row,
  Segmented,
  Select,
  Space,
  Statistic,
  Table,
  Tabs,
  Tag,
  Typography,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { api } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import FaceAuthPanel from '../components/FaceAuthPanel'
import { presentJobName, presentStudentOption } from '../utils/present'
import ace from 'ace-builds'
import 'ace-builds/src-noconflict/ext-language_tools'
import 'ace-builds/src-noconflict/theme-monokai'
import 'ace-builds/src-noconflict/theme-github'
import 'ace-builds/src-noconflict/mode-java'
import 'ace-builds/src-noconflict/mode-python'
import 'ace-builds/src-noconflict/mode-golang'
import 'ace-builds/src-noconflict/mode-c_cpp'
import 'ace-builds/src-noconflict/mode-rust'

const { Text, Paragraph, Title } = Typography
const LATEST_CODING_ASSESSMENT_KEY = 'interview.latestCodingAssessment'

type CodeLanguage = 'java' | 'cpp' | 'python' | 'go' | 'rust'

const LANGUAGE_OPTIONS: Array<{ label: string; value: CodeLanguage }> = [
  { label: 'Java', value: 'java' },
  { label: 'C++', value: 'cpp' },
  { label: 'Python', value: 'python' },
  { label: 'Go', value: 'go' },
  { label: 'Rust', value: 'rust' },
]

function CodeEditor({
  value,
  language,
  onChange,
}: {
  value: string
  language: CodeLanguage
  onChange: (value: string) => void
}) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const editorRef = useRef<ace.Ace.Editor | null>(null)
  const mode = language === 'cpp' ? 'c_cpp' : language === 'go' ? 'golang' : language

  useEffect(() => {
    if (!containerRef.current || editorRef.current) return
    const editor = ace.edit(containerRef.current, {
      theme: 'ace/theme/monokai',
      mode: `ace/mode/${mode}`,
      fontSize: 14,
      tabSize: 4,
      useSoftTabs: true,
      showPrintMargin: false,
      wrap: true,
      enableBasicAutocompletion: true,
      enableLiveAutocompletion: true,
      enableSnippets: true,
    })
    editor.session.setValue(value || '')
    editor.session.on('change', () => onChange(editor.session.getValue()))
    editorRef.current = editor
    return () => {
      editor.destroy()
      editorRef.current = null
    }
  }, [])

  useEffect(() => {
    const editor = editorRef.current
    if (!editor) return
    editor.session.setMode(`ace/mode/${mode}`)
  }, [mode])

  useEffect(() => {
    const editor = editorRef.current
    if (!editor) return
    if (editor.session.getValue() !== value) {
      const cursor = editor.getCursorPosition()
      editor.session.setValue(value || '')
      editor.moveCursorToPosition(cursor)
      editor.clearSelection()
    }
  }, [value])

  return <div ref={containerRef} className="coding-ace-editor" aria-label={`${language} code editor`} />
}

type StudentItem = { student_id: string; name?: string }

type JobItem = {
  job_id: string
  title?: string
  description?: string
  company_name?: string
  location?: string
  overall_score?: number | null
  _source?: 'smart' | 'search'
}

type ReportItem = { report_id: string; version?: number; updated_at?: string; created_at?: string }

type CodingChallenge = {
  challenge_id?: string
  problem_id?: string
  title?: string
  difficulty?: string
  language?: string
  language_label?: string
  tags?: string[]
  question?: string
  background?: string
  statement?: string
  input_format?: string
  output_format?: string
  samples?: Array<{ input?: string; output?: string; explanation?: string }>
  data_range?: string[]
  constraints?: string[]
  examples?: Array<{ input?: string; output?: string; explanation?: string } | string>
  input_example?: string
  output_example?: string
  starter_code?: string
  code?: string
  input?: string
  output?: string
  round?: string
  evaluation_points?: string[]
  hints?: string[]
  expected_complexity?: Record<string, string>
  demo_code?: string
  submission_mode?: string
  submission_tip?: string
  practice_plan?: string[]
  llm_used?: boolean
}

type CodingReview = {
  overall_score?: number
  dimension_scores?: Record<string, number>
  strengths?: string[]
  issues?: string[]
  improvement_steps?: string[]
  reference_solution?: string
  interview_note?: string
  llm_used?: boolean
}

type JudgeCase = {
  case_id: string
  name: string
  input: string
  expected: string
  actual: string
  status: string
  sample?: boolean
  time_ms?: number
  memory_kb?: number
  message?: string
}

type JudgeResult = {
  submission_id: string
  engine: string
  container?: Record<string, any>
  problem_id: string
  language: string
  status: string
  status_text: string
  score: number
  passed_cases: number
  total_cases: number
  cases: JudgeCase[]
  message: string
  sample_only?: boolean
}

function rememberLatestCodingAssessment(payload: {
  student_id: string
  job_id?: string
  challenge: CodingChallenge
  review: CodingReview
}) {
  if (typeof window === 'undefined') return
  window.localStorage.setItem(personalStorageKey(LATEST_CODING_ASSESSMENT_KEY), JSON.stringify({
    ...payload,
    updated_at: new Date().toISOString(),
  }))
}

function verdictColor(status?: string) {
  if (status === 'AC') return 'success'
  if (status === 'CE') return 'error'
  if (status === 'WA') return 'warning'
  return 'default'
}

export default function InterviewCodingTest() {
  const { message } = App.useApp()
  const { canWrite } = useAuth()
  const [students, setStudents] = useState<StudentItem[]>([])
  const [jobs, setJobs] = useState<JobItem[]>([])
  const [reports, setReports] = useState<ReportItem[]>([])
  const [studentId, setStudentId] = useState('')
  const [jobId, setJobId] = useState('')
  const [reportId, setReportId] = useState('')
  const [jobSearchKeyword, setJobSearchKeyword] = useState('')
  const [jobLoading, setJobLoading] = useState(false)
  const [codeLanguage, setCodeLanguage] = useState<CodeLanguage>('python')
  const [codingFirst, setCodingFirst] = useState(true)
  const [codingChallenge, setCodingChallenge] = useState<CodingChallenge | null>(null)
  const [codeText, setCodeText] = useState('')
  const [codingReview, setCodingReview] = useState<CodingReview | null>(null)
  const [judgeResult, setJudgeResult] = useState<JudgeResult | null>(null)
  const [loadingCoding, setLoadingCoding] = useState(false)
  const [loadingJudge, setLoadingJudge] = useState(false)
  const [loadingCodingReview, setLoadingCodingReview] = useState(false)
  const jobQuerySeqRef = useRef(0)

  const codeStats = useMemo(() => {
    const lines = codeText.split(/\r?\n/).filter(line => line.trim()).length
    const hasPlaceholder = /请补全|在这里实现|请在这里实现|请实现|初始化缓存结构|查询并刷新访问顺序|写入并处理淘汰|定义缓存结构/.test(codeText)
    const algorithmSignals = /HashMap|Map<|dict|unordered_map|map\[|HashMap::new|stack|deque|window|write/.test(codeText)
    const designSignals = /synchronized|volatile|static\s+class|sync\.Once|OnceLock|threading\.Lock|delete/.test(codeText)
    return { lines, hasPlaceholder, likelyTouchedCore: codingFirst ? algorithmSignals : designSignals }
  }, [codeText, codingFirst])

  const searchStudents = async (keyword: string = '') => {
    const res = await api.get('/students', { params: { limit: 200, offset: 0, q: keyword || undefined } })
    const items = (res.data?.items || []) as StudentItem[]
    setStudents(items)
    return items
  }

  const searchJobs = async (keyword: string = '') => {
    const res = await api.get('/jobs', { params: { limit: keyword ? 120 : 80, offset: 0, q: keyword || undefined } })
    const items = (res.data?.items || []) as JobItem[]
    return items.map(item => ({ ...item, _source: 'search' as const }))
  }

  const loadJobCandidates = async (keyword: string = '') => {
    const q = String(keyword || '').trim()
    const currentSeq = ++jobQuerySeqRef.current
    setJobLoading(true)
    try {
      const searchedJobs = q.length >= 2 || !studentId ? await searchJobs(q) : []
      if (currentSeq !== jobQuerySeqRef.current) return
      setJobs(searchedJobs)
    } catch {
      if (currentSeq !== jobQuerySeqRef.current) return
      setJobs([])
    } finally {
      if (currentSeq === jobQuerySeqRef.current) setJobLoading(false)
    }
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
    searchStudents()
      .then(items => {
        if (!studentId && items.length) setStudentId(items[0].student_id)
      })
      .catch(() => message.error('加载笔试基础数据失败'))
  }, [])

  useEffect(() => {
    if (!studentId) return
    loadReports(studentId).catch(() => {
      setReports([])
      setReportId('')
    })
  }, [studentId])

  useEffect(() => {
    const timer = window.setTimeout(() => { void loadJobCandidates(jobSearchKeyword) }, 320)
    return () => window.clearTimeout(timer)
  }, [studentId, jobSearchKeyword])

  const studentOptions = useMemo(
    () => students.map((item, index) => ({ label: presentStudentOption(item, index), value: item.student_id })),
    [students],
  )

  const jobOptions = useMemo(() => {
    const options = jobs.map((item, index) => {
      const parts = [presentJobName(item, index)]
      if (item.company_name) parts.push(String(item.company_name))
      if (item.location) parts.push(String(item.location))
      if (item.job_id) parts.push(`ID:${item.job_id}`)
      return { label: parts.join(' · '), value: item.job_id }
    })
    return [{ label: '不指定岗位', value: '' }, ...options]
  }, [jobs])

  const reportOptions = useMemo(
    () => reports.map(item => {
      const time = String(item.updated_at || item.created_at || '').replace('T', ' ').slice(0, 16)
      return { label: `${item.report_id}${item.version ? ` · v${item.version}` : ''}${time ? ` · ${time}` : ''}`, value: item.report_id }
    }),
    [reports],
  )

  const startCodingChallenge = async (firstOverride = codingFirst, languageOverride: CodeLanguage = codeLanguage) => {
    if (!studentId) {
      message.warning('请先选择学生')
      return
    }
    setCodingFirst(firstOverride)
    setCodeLanguage(languageOverride)
    setLoadingCoding(true)
    try {
      const res = await api.post('/interview/coding/start', {
        student_id: studentId,
        job_id: jobId || undefined,
        language: languageOverride,
        difficulty: 'medium',
        first: firstOverride,
      })
      const data = res.data as CodingChallenge
      setCodingChallenge(data)
      setCodeLanguage((data.language as CodeLanguage) || languageOverride)
      setCodeText(String(data.starter_code || data.code || ''))
      setCodingReview(null)
      setJudgeResult(null)
      message.success('已生成笔试题')
    } catch (e: any) {
      message.error(e?.response?.data?.detail?.message || '生成代码题失败')
    } finally {
      setLoadingCoding(false)
    }
  }

  const changeLanguage = (value: CodeLanguage) => {
    setCodeLanguage(value)
    setCodingReview(null)
    setJudgeResult(null)
    if (codingChallenge) {
      void startCodingChallenge(codingFirst, value)
      return
    }
    setCodeText('')
  }

  const judgeCode = async (sampleOnly = false) => {
    if (!codingChallenge || !codeText.trim()) {
      message.warning('请先生成笔试题并填写代码')
      return
    }
    setLoadingJudge(true)
    try {
      const res = await api.post('/interview/coding/judge', {
        student_id: studentId,
        job_id: jobId || undefined,
        challenge: codingChallenge,
        code: codeText,
        sample_only: sampleOnly,
      })
      const result = res.data as JudgeResult
      setJudgeResult(result)
      message[result.status === 'AC' ? 'success' : 'warning'](`${sampleOnly ? '样例运行' : '提交判题'}：${result.status_text}`)
    } catch (e: any) {
      message.error(e?.response?.data?.detail?.message || '判题失败')
    } finally {
      setLoadingJudge(false)
    }
  }

  const reviewCodingAnswer = async () => {
    if (!canWrite) {
      message.warning('只读角色不可提交代码小测')
      return
    }
    if (!codingChallenge || !codeText.trim()) {
      message.warning('请先生成笔试题并填写代码')
      return
    }
    setLoadingCodingReview(true)
    try {
      const res = await api.post('/interview/coding/review', {
        student_id: studentId,
        job_id: jobId || undefined,
        challenge: codingChallenge,
        code: codeText,
      })
      const review = (res.data || null) as CodingReview | null
      setCodingReview(review)
      if (review) rememberLatestCodingAssessment({ student_id: studentId, job_id: jobId || '', challenge: codingChallenge, review })
      message.success('代码点评完成，已关联到本轮能力复盘')
    } catch (e: any) {
      message.error(e?.response?.data?.detail?.message || '代码点评失败')
    } finally {
      setLoadingCodingReview(false)
    }
  }

  const resetStarterCode = () => {
    if (!codingChallenge) return
    setCodeText(String(codingChallenge.starter_code || codingChallenge.code || ''))
    setJudgeResult(null)
  }

  const loadDemoSolution = () => {
    if (!codingChallenge?.demo_code) return
    setCodeText(codingChallenge.demo_code)
    setJudgeResult(null)
    message.success('已载入参考代码，适合演示 AC 流程')
  }

  const appendCodingToReport = async () => {
    if (!canWrite) {
      message.warning('只读角色不可写入报告')
      return
    }
    if (!codingChallenge || !codingReview) {
      message.warning('请先完成代码点评')
      return
    }
    if (!reportId) {
      message.warning('当前学生暂无可写入的报告，请先在规划报告页生成报告')
      return
    }
    const plan = [...(codingChallenge.practice_plan || []), ...(codingReview.improvement_steps || [])].filter(Boolean)
    const payload = {
      summary: codingReview.interview_note || '已完成岗位代码小测，建议把暴露出的技能短板纳入短期补强计划。',
      overall_score: codingReview.overall_score || 0,
      strengths: codingReview.strengths || [],
      priority_gaps: codingReview.issues || [],
      action_items: plan.slice(0, 6),
      coding_practice_plan: plan.slice(0, 6),
      report_markdown: `### 岗位技能验证\n- 笔试题：${codingChallenge.title || '代码小测'}\n- 判题结果：${judgeResult?.status_text || '未提交判题'} ${judgeResult ? `(${judgeResult.passed_cases}/${judgeResult.total_cases})` : ''}\n- 综合分：${codingReview.overall_score || 0}\n- 验证结论：${codingReview.interview_note || '建议继续补强代码实现、边界处理和复杂度表达。'}\n`,
      coding_review: { ...codingReview, judge_result: judgeResult },
      coding_challenge: codingChallenge,
    }
    try {
      await api.post(`/reports/${reportId}/append_interview_summary`, payload)
      message.success('代码小测结果已写入职业规划报告')
      await loadReports(studentId)
    } catch (e: any) {
      message.error(e?.response?.data?.detail?.message || e?.response?.data?.error || '写入报告失败')
    }
  }

  const judgeColumns: ColumnsType<JudgeCase> = [
    { title: '测试点', dataIndex: 'name', key: 'name', width: 190 },
    { title: '类型', dataIndex: 'sample', key: 'sample', width: 76, render: value => <Tag>{value ? '样例' : '隐藏'}</Tag> },
    { title: '状态', dataIndex: 'status', key: 'status', width: 96, render: value => <Tag color={verdictColor(value)}>{value}</Tag> },
    { title: '耗时', dataIndex: 'time_ms', key: 'time_ms', width: 86, render: value => `${value || 0} ms` },
    { title: '内存', dataIndex: 'memory_kb', key: 'memory_kb', width: 96, render: value => `${Math.round(Number(value || 0) / 1024)} MB` },
    {
      title: '输出对比',
      key: 'io',
      render: (_, row) => (
        <div className="judge-io">
          <Text type="secondary">期望</Text>
          <code>{row.expected}</code>
          <Text type="secondary">实际</Text>
          <code>{row.actual}</code>
        </div>
      ),
    },
  ]

  return (
    <Space direction="vertical" size={18} style={{ width: '100%' }}>
      {!canWrite ? <Alert type="info" showIcon message="当前账号为只读角色，可查看笔试题，但不可提交代码点评。" /> : null}
      <FaceAuthPanel compact title="笔试身份认证" />

      <Card className="coding-workbench-card" title="在线笔试" extra={<Tag color="geekblue">标准判题</Tag>}>
        <Space direction="vertical" size={14} style={{ width: '100%' }}>
          <Row gutter={[12, 12]}>
            <Col xs={24} md={8}>
              <Text type="secondary">学生</Text>
              <Select style={{ width: '100%', marginTop: 6 }} value={studentId} onChange={setStudentId} options={studentOptions} showSearch filterOption={false} onSearch={value => { void searchStudents(String(value || '').trim()) }} />
            </Col>
            <Col xs={24} md={10}>
              <Text type="secondary">目标岗位</Text>
              <Select style={{ width: '100%', marginTop: 6 }} value={jobId} onChange={setJobId} options={jobOptions} showSearch filterOption={false} loading={jobLoading} onSearch={value => setJobSearchKeyword(String(value || '').trim())} notFoundContent={jobLoading ? '岗位搜索中...' : '暂无匹配岗位，可输入岗位ID/岗位名/公司/技能关键词'} />
            </Col>
            <Col xs={24} md={6}>
              <Text type="secondary">编程语言</Text>
              <Segmented block className="coding-language-segment" value={codeLanguage} onChange={value => changeLanguage(value as CodeLanguage)} options={LANGUAGE_OPTIONS} />
            </Col>
            <Col xs={24} md={6}>
              <Text type="secondary">题目类型</Text>
              <Select style={{ width: '100%', marginTop: 6 }} value={codingFirst ? 'algorithm' : 'design'} onChange={value => setCodingFirst(value === 'algorithm')} options={[{ label: '算法题', value: 'algorithm' }, { label: '工程设计题', value: 'design' }]} />
            </Col>
            <Col xs={24} md={8}>
              <Text type="secondary">写入目标报告</Text>
              <Select style={{ width: '100%', marginTop: 6 }} value={reportId} onChange={setReportId} options={reportOptions} placeholder="当前学生暂无报告" notFoundContent="当前学生暂无报告，请先生成职业规划报告" />
            </Col>
          </Row>
          <Space wrap>
            <Button type="primary" loading={loadingCoding} onClick={() => void startCodingChallenge()}>{codingChallenge ? '换一道题' : '开始笔试'}</Button>
            <Button onClick={() => void startCodingChallenge(false)} disabled={loadingCoding}>工程题</Button>
            <Button onClick={resetStarterCode} disabled={!codingChallenge}>恢复模板</Button>
            <Button onClick={loadDemoSolution} disabled={!codingChallenge?.demo_code}>参考代码</Button>
            <Button loading={loadingJudge} onClick={() => void judgeCode(true)} disabled={!codingChallenge}>运行样例</Button>
            <Button type="primary" loading={loadingJudge} onClick={() => void judgeCode(false)} disabled={!codingChallenge}>提交判题</Button>
            <Button loading={loadingCodingReview} onClick={() => void reviewCodingAnswer()} disabled={!codingChallenge || !canWrite}>AI 点评</Button>
            <Button onClick={() => void appendCodingToReport()} disabled={!codingReview || !reportId || !canWrite}>写入规划报告</Button>
          </Space>
        </Space>
      </Card>

      {codingChallenge ? (
        <Row gutter={[16, 16]} className="coding-workbench-grid">
          <Col xs={24} xl={10}>
            <Card className="coding-problem-card">
              <article className="oj-problem">
                <header className="oj-problem-header">
                  <Text type="secondary">{codingChallenge.problem_id || (codingChallenge.round === 'design' ? 'D2001' : 'G1001')}</Text>
                  <Title level={3}>{codingChallenge.title || '笔试题'}</Title>
                  <Space wrap>
                    <Tag color="blue">{codingChallenge.language_label || codingChallenge.language || codeLanguage}</Tag>
                    <Tag color="purple">{codingChallenge.round === 'design' ? '工程设计题' : '算法题'}</Tag>
                    <Tag color="cyan">{codingChallenge.difficulty || '中等'}</Tag>
                    <Tag color="green">标准评测</Tag>
                  </Space>
                </header>

                {codingChallenge.tags?.length ? <Space size={[0, 8]} wrap>{codingChallenge.tags.map(item => <Tag key={item}>{item}</Tag>)}</Space> : null}
                <section className="oj-section"><Title level={4}>题目描述</Title><Paragraph>{codingChallenge.statement || codingChallenge.question}</Paragraph></section>
                <section className="oj-section"><Title level={4}>输入格式</Title><Paragraph>{codingChallenge.input_format || codingChallenge.input_example || codingChallenge.input || '-'}</Paragraph></section>
                <section className="oj-section"><Title level={4}>输出格式</Title><Paragraph>{codingChallenge.output_format || codingChallenge.output_example || codingChallenge.output || '-'}</Paragraph></section>
                <section className="oj-section">
                  <Title level={4}>输入输出样例</Title>
                  <List
                    className="oj-sample-list"
                    dataSource={(codingChallenge.samples?.length ? codingChallenge.samples : codingChallenge.examples || [])}
                    renderItem={(item, index) => {
                      const row = typeof item === 'string' ? { input: item } : item
                      return (
                        <List.Item>
                          <div className="oj-sample">
                            <div className="oj-sample-block">
                              <p className="oj-sample-caption"><b>输入 #{index + 1}</b></p>
                              <pre className="oj-sample-code">{row.input || '-'}</pre>
                            </div>
                            <div className="oj-sample-block">
                              <p className="oj-sample-caption"><b>输出 #{index + 1}</b></p>
                              <pre className="oj-sample-code">{row.output || '-'}</pre>
                            </div>
                            {row.explanation ? <Paragraph className="oj-sample-explanation" type="secondary">{row.explanation}</Paragraph> : null}
                          </div>
                        </List.Item>
                      )
                    }}
                  />
                </section>
                {codingChallenge.data_range?.length || codingChallenge.constraints?.length ? (
                  <section className="oj-section">
                    <Title level={4}>数据范围</Title>
                    <List size="small" dataSource={[...(codingChallenge.data_range || []), ...(codingChallenge.constraints || [])]} renderItem={item => <List.Item>{item}</List.Item>} />
                  </section>
                ) : null}
                {codingChallenge.expected_complexity ? (
                  <section className="oj-section">
                    <Title level={4}>期望复杂度</Title>
                    <Space wrap><Tag>时间 {codingChallenge.expected_complexity.time || '-'}</Tag><Tag>空间 {codingChallenge.expected_complexity.space || '-'}</Tag></Space>
                  </section>
                ) : null}
              </article>
            </Card>
          </Col>
          <Col xs={24} xl={14}>
            <Card
              className="coding-editor-card"
              title="代码编辑区"
              extra={<Space wrap><Tag color={codeStats.hasPlaceholder ? 'orange' : 'green'}>{codeStats.hasPlaceholder ? '待补全' : '已修改'}</Tag><Tag>{codeStats.lines} 行</Tag></Space>}
            >
              <CodeEditor value={codeText} language={codeLanguage} onChange={value => { setCodeText(value); setJudgeResult(null) }} />
              <div className="judge-console">
                <Tabs
                  size="small"
                  items={[
                    {
                      key: 'result',
                      label: '判题结果',
                      children: judgeResult ? (
                        <Space direction="vertical" size={12} style={{ width: '100%' }}>
                          <div className="judge-summary">
                            <div>
                              <Tag color={verdictColor(judgeResult.status)} className="judge-verdict">{judgeResult.status_text}</Tag>
                            </div>
                            <Progress type="circle" size={76} percent={judgeResult.score} status={judgeResult.status === 'AC' ? 'success' : 'exception'} />
                          </div>
                          <Row gutter={[10, 10]}>
                            <Col xs={12} md={6}><Statistic title="通过" value={`${judgeResult.passed_cases}/${judgeResult.total_cases}`} /></Col>
                            <Col xs={12} md={6}><Statistic title="状态" value={judgeResult.status} /></Col>
                            <Col xs={12} md={6}><Statistic title="时间限制" value={judgeResult.container?.time_limit_ms || 1000} suffix="ms" /></Col>
                            <Col xs={12} md={6}><Statistic title="内存限制" value={judgeResult.container?.memory_limit_mb || 128} suffix="MB" /></Col>
                          </Row>
                          <Alert type={judgeResult.status === 'AC' ? 'success' : 'warning'} showIcon message={judgeResult.message} />
                          <Table rowKey="case_id" size="small" columns={judgeColumns} dataSource={judgeResult.cases} pagination={false} scroll={{ x: 820 }} />
                        </Space>
                      ) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="点击运行样例或提交判题" />,
                    },
                    {
                      key: 'stdin',
                      label: '样例输入',
                      children: <pre className="judge-plain">{codingChallenge.input || codingChallenge.input_example || '-'}</pre>,
                    },
                  ]}
                />
              </div>
            </Card>
          </Col>
        </Row>
      ) : <Empty description="点击“开始笔试”后开始" />}

      {codingReview ? (
        <Card title="代码点评结果">
          <Space direction="vertical" size={12} style={{ width: '100%' }}>
            <Row gutter={[12, 12]}>
              <Col xs={24} md={6}><Statistic title="综合分" value={codingReview.overall_score || 0} /></Col>
              {Object.entries(codingReview.dimension_scores || {}).map(([key, value]) => <Col xs={12} md={6} key={key}><Statistic title={key} value={value} /></Col>)}
            </Row>
            <Row gutter={[12, 12]}>
              <Col xs={24} md={8}><Title level={5}>亮点</Title><List size="small" dataSource={codingReview.strengths || []} renderItem={item => <List.Item>{item}</List.Item>} /></Col>
              <Col xs={24} md={8}><Title level={5}>问题</Title><List size="small" dataSource={codingReview.issues || []} renderItem={item => <List.Item>{item}</List.Item>} /></Col>
              <Col xs={24} md={8}><Title level={5}>改进步骤</Title><List size="small" dataSource={codingReview.improvement_steps || []} renderItem={item => <List.Item>{item}</List.Item>} /></Col>
            </Row>
            {codingReview.interview_note ? <Alert type="info" showIcon message="岗位技能验证结论" description={codingReview.interview_note} /> : null}
            {codingChallenge?.practice_plan?.length ? (
              <>
                <Divider orientation="left">后续补强计划</Divider>
                <List size="small" dataSource={codingChallenge.practice_plan} renderItem={(item, index) => <List.Item>{index + 1}. {item}</List.Item>} />
              </>
            ) : null}
          </Space>
        </Card>
      ) : null}
    </Space>
  )
}
