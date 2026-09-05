import React, { useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
  Alert,
  App,
  Button,
  Card,
  Col,
  Descriptions,
  Empty,
  Input,
  List,
  Progress,
  Row,
  Segmented,
  Select,
  Space,
  Tag,
  Timeline,
  Typography
} from 'antd'
import {
  CheckCircleOutlined,
  CopyOutlined,
  DownloadOutlined,
  EditOutlined,
  EyeOutlined,
  FileTextOutlined,
  ReloadOutlined,
  RocketOutlined,
  SaveOutlined,
  SyncOutlined,
  ThunderboltOutlined
} from '@ant-design/icons'
import ReactMarkdown from 'react-markdown'
import { api, apiUrl } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { PathFlow, PathFlowList } from '../components/CareerPathViz'
import { familyLabel } from '../constants/labels'
import { presentIssueType, presentReportLabel, presentRoleName, presentSeverity, presentStudentOption } from '../utils/present'

const { Title, Text, Paragraph } = Typography

const DIMENSION_LABELS: Record<string, string> = {
  basic: '基础要求',
  skills: '职业技能',
  literacy: '职业素养',
  potential: '发展潜力',
  stability: '岗位稳定性'
}

const POLISH_STYLE_OPTIONS = [
  { label: '专业版', value: 'professional' },
  { label: '顾问版', value: 'advisor' },
  { label: '精简版', value: 'concise' }
]

function formatTimeLabel(value?: string) {
  if (!value) return '-'
  return value.replace('T', ' ').replace(/\+.*$/, '').slice(0, 19)
}

function reportSections(markdown: string) {
  return (markdown || '')
    .split('\n')
    .map(line => line.trim())
    .filter(line => /^##\s+/.test(line))
    .map(line => line.replace(/^##\s+/, ''))
}

function countActionItems(actionPlan: any[]) {
  return (actionPlan || []).reduce((sum, phase) => sum + ((phase?.actions || []).length), 0)
}

function safeIssues(raw: any) {
  if (!raw) return [] as any[]
  if (Array.isArray(raw)) {
    return raw.map((item: any) => typeof item === 'string' ? { type: 'plain', severity: 'medium', message: item } : item)
  }
  return [] as any[]
}

function targetRoleName(role: any) {
  if (!role) return '待选定方向'
  return `${presentRoleName(role)} / ${role.job_family_label || familyLabel(role.job_family)}`
}

export default function ReportStudio() {
  const { message } = App.useApp()
  const { canWrite } = useAuth()
  const [searchParams] = useSearchParams()
  const queryStudentId = searchParams.get('student_id') || undefined
  const queryRoleId = searchParams.get('role_id') || undefined
  const queryReportId = searchParams.get('report_id') || undefined
  const queryTargetJobId = searchParams.get('target_job_id') || undefined
  const queryAutoGenerateJob = ['1', 'true', 'yes'].includes(String(searchParams.get('auto_generate_job') || '').toLowerCase())

  const [students, setStudents] = useState<any[]>([])
  const [roles, setRoles] = useState<any[]>([])
  const [studentId, setStudentId] = useState<string | undefined>(queryStudentId)
  const [roleId, setRoleId] = useState<string | undefined>(queryRoleId)
  const [report, setReport] = useState<any>(null)
  const [markdown, setMarkdown] = useState('')
  const [reports, setReports] = useState<any[]>([])
  const [checking, setChecking] = useState<any>(null)
  const [loading, setLoading] = useState(false)
  const [mode, setMode] = useState<'preview' | 'edit' | 'outline'>('preview')
  const [polishStyle, setPolishStyle] = useState<string>('professional')
  const autoJobGenerateStartedRef = React.useRef(false)

  const selectedStudent = useMemo(() => students.find(item => item.student_id === studentId), [students, studentId])
  const selectedRole = useMemo(() => roles.find(item => item.role_id === roleId), [roles, roleId])

  const studentOptions = useMemo(() => (
    students.map((s, index) => ({ label: presentStudentOption(s, index), value: s.student_id }))
  ), [students])

  const roleOptions = useMemo(() => (
    roles.map((r, index) => ({ label: `${presentRoleName(r, index)} / ${r.job_family_label || familyLabel(r.job_family)}（岗位样本 ${r.member_count || 0}）`, value: r.role_id }))
  ), [roles])

  const loadReports = async (sid?: string) => {
    if (!sid) return
    const res = await api.get(`/students/${sid}/reports`)
    setReports(res.data.items || [])
  }

  const refreshCheck = async (reportId?: string) => {
    if (!reportId) {
      setChecking(null)
      return
    }
    try {
      const res = await api.post(`/reports/${reportId}/check`)
      setChecking(res.data)
    } catch {
      setChecking(null)
    }
  }

  const loadReport = async (reportId: string) => {
    const res = await api.get(`/reports/${reportId}`)
    const data = {
      report_id: res.data.report_id,
      student_id: res.data.student_id,
      version: res.data.version,
      created_at: res.data.created_at,
      updated_at: res.data.updated_at,
      ...(res.data.content_json || {}),
      content_md: res.data.content_md
    }
    setReport(data)
    setMarkdown(res.data.content_md || '')
    if (res.data.student_id) setStudentId(res.data.student_id)
    const nextRoleId = res.data.content_json?.career_path?.role_id || res.data.content_json?.role_id
    if (nextRoleId) setRoleId(nextRoleId)
    await refreshCheck(reportId)
  }

  const loadMeta = async () => {
    const [studentsRes, rolesRes] = await Promise.all([
      api.get('/students', { params: { limit: 200, offset: 0 } }),
      api.get('/insights/role_samples', { params: { top_k: 50 } })
    ])
    const studentItems = studentsRes.data.items || []
    const roleItems = (rolesRes.data.items || []).filter((r: any) => Number(r?.member_count || 0) > 0)
    setStudents(studentItems)
    setRoles(roleItems)
    if (!studentId && studentItems.length) setStudentId(studentItems[0].student_id)
    if (!roleId && roleItems.length) setRoleId(roleItems[0].role_id)
  }

  const searchStudents = async (keyword: string = '') => {
    const res = await api.get('/students', {
      params: { limit: 200, offset: 0, q: keyword || undefined }
    })
    const items = Array.isArray(res.data?.items) ? res.data.items : []
    setStudents(items)
  }

  useEffect(() => {
    void loadMeta()
  }, [])

  useEffect(() => {
    void loadReports(studentId)
  }, [studentId])

  useEffect(() => {
    if (queryReportId) {
      void loadReport(queryReportId)
    }
  }, [queryReportId])

  useEffect(() => {
    if (!queryAutoGenerateJob) return
    if (!queryTargetJobId) return
    if (!studentId) return
    if (!canWrite) return
    if (autoJobGenerateStartedRef.current) return
    autoJobGenerateStartedRef.current = true
    void generateReportByTargetJob(queryTargetJobId)
  }, [queryAutoGenerateJob, queryTargetJobId, studentId, canWrite])

  const generateReport = async () => {
    if (!canWrite) {
      message.warning('只读角色不可生成报告。')
      return
    }
    if (!studentId || !roleId) {
      message.warning('请选择学生和目标方向。')
      return
    }
    setLoading(true)
    try {
      const res = await api.post('/reports/generate_for_role', { student_id: studentId, role_id: roleId })
      if (res?.data?.error) {
        const reason = res.data.error === 'role_has_no_jobs' ? '该方向当前没有岗位样本，请换一个方向再试。' : `生成失败：${res.data.error}`
        message.error(reason)
        return
      }
      const newReport = {
        ...res.data,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        content_md: res.data.markdown
      }
      setReport(newReport)
      setMarkdown(res.data.markdown || '')
      setMode('preview')
      message.success('职业报告已生成')
      await loadReports(studentId)
      await refreshCheck(res.data.report_id)
    } catch (e: any) {
      const msg = e?.response?.data?.detail || e?.message || '请求失败，请稍后重试'
      message.error(`生成失败：${msg}`)
    } finally {
      setLoading(false)
    }
  }

  const generateReportByTargetJob = async (targetJobId?: string) => {
    const jobId = String(targetJobId || '').trim()
    if (!canWrite) {
      message.warning('只读角色不可生成报告。')
      return
    }
    if (!studentId || !jobId) {
      message.warning('缺少学生或目标岗位，无法生成单岗位报告。')
      return
    }
    setLoading(true)
    try {
      const res = await api.post('/reports/generate', { student_id: studentId, target_job_ids: [jobId] })
      if (res?.data?.error) {
        message.error(`生成失败：${res.data.error}`)
        return
      }
      const now = new Date().toISOString()
      const newReport = {
        ...res.data,
        created_at: res.data?.created_at || now,
        updated_at: res.data?.updated_at || now,
        content_md: res.data?.markdown || ''
      }
      setReport(newReport)
      setMarkdown(String(res.data?.markdown || ''))
      const nextRoleId = String(res.data?.career_path?.role_id || '').trim()
      if (nextRoleId) {
        setRoleId(nextRoleId)
      }
      setMode('preview')
      message.success('已基于心仪岗位生成报告')
      await loadReports(studentId)
      await refreshCheck(res.data?.report_id)
    } catch (e: any) {
      const msg = e?.response?.data?.detail || e?.message || '请求失败，请稍后重试'
      message.error(`生成失败：${msg}`)
    } finally {
      setLoading(false)
    }
  }

  const saveReport = async () => {
    if (!canWrite || !report?.report_id) return
    await api.put(`/reports/${report.report_id}`, {
      content_md: markdown,
      content_json: {
        ...(report || {}),
        markdown
      }
    })
    message.success('报告已保存')
    await loadReports(studentId)
    await loadReport(report.report_id)
  }

  const polishReport = async () => {
    if (!canWrite || !report?.report_id) return
    setLoading(true)
    try {
      const res = await api.post(`/reports/${report.report_id}/polish`, { style: polishStyle, apply: true })
      setMarkdown(res.data.markdown || '')
      message.success('报告已润色并应用')
      await loadReport(report.report_id)
    } catch (e: any) {
      const msg = e?.response?.data?.detail || e?.message || '请求失败，请稍后重试'
      message.error(`润色失败：${msg}`)
    } finally {
      setLoading(false)
    }
  }

  const copyMarkdown = async () => {
    try {
      await navigator.clipboard.writeText(markdown)
      message.success('已复制当前文本稿内容')
    } catch {
      message.warning('复制失败，请手动选择内容复制')
    }
  }

  const fitAnalysis = report?.fit_analysis || {}
  const careerPath = report?.career_path || {}
  const planningContext = careerPath?.planning_context || report?.planning_context || {}
  const studentSnapshot = report?.student_snapshot || {}
  const actionPlan = report?.action_plan || []
  const evaluation = report?.evaluation || {}
  const issues = safeIssues(checking?.issues)
  const hasReport = Boolean(report?.report_id)
  const hasChecked = hasReport && checking && !checking?.error

  const qualityScore = Math.max(35, 100 - issues.length * 12)
  const sections = reportSections(markdown)
  const overallScore = Number(fitAnalysis?.overall_score || 0)
  const strengths = (fitAnalysis?.top_strengths || []).filter(Boolean)
  const gaps = (fitAnalysis?.top_gaps || []).filter(Boolean)
  const actionItemCount = countActionItems(actionPlan)
  const verticalPathNodes = (careerPath?.role_vertical_path || careerPath?.vertical_path || []).filter(Boolean)
  const switchPathNodes = (careerPath?.role_switch_paths || careerPath?.switch_paths || []).map((path: any) => {
    if (Array.isArray(path?.nodes)) return path.nodes
    if (Array.isArray(path)) return path
    return []
  }).filter((path: any[]) => path.length)

  const heroStats = [
    { label: '匹配得分', value: overallScore ? overallScore.toFixed(1) : '-', suffix: '分', tone: 'primary' },
    { label: '优势标签', value: strengths.length || 0, suffix: '项', tone: 'success' },
    { label: '关键差距', value: gaps.length || 0, suffix: '项', tone: 'warning' },
    { label: '行动计划', value: actionItemCount || 0, suffix: '条', tone: 'secondary' }
  ]

  const dimensionRows = Object.entries(fitAnalysis?.dimension_scores || {}).map(([key, value]: [string, any]) => ({
    key,
    label: DIMENSION_LABELS[key] || key,
    score: typeof value === 'object' ? Number(value?.score || 0) : Number(value || 0)
  }))

  const reportSummaryRows = [
    { label: '学生档案', value: selectedStudent ? presentStudentOption(selectedStudent) : '待选择学生' },
    { label: 'MBTI', value: studentSnapshot?.mbti_type ? `${studentSnapshot.mbti_type}${studentSnapshot?.mbti_label ? `（${studentSnapshot.mbti_label}）` : ''}` : '未填写' },
    { label: '目标方向', value: selectedRole ? targetRoleName(selectedRole) : '待选定方向' },
    { label: '目标岗位', value: careerPath?.target_job?.title || '待自动确定' },
    {
      label: '样本企业（非唯一目标）',
      value: Array.isArray(planningContext?.top_companies) && planningContext.top_companies.length
        ? planningContext.top_companies.slice(0, 5).join('、')
        : (careerPath?.target_job?.company || '待补全')
    },
    {
      label: '岗位簇关键词',
      value: Array.isArray(planningContext?.market_keywords) && planningContext.market_keywords.length
        ? planningContext.market_keywords.slice(0, 10).join('、')
        : '待生成'
    },
    { label: '选中岗位ID', value: careerPath?.target_job?.job_id || '待补全' },
    { label: '候选岗位样本数', value: Number(report?.target_jobs?.length || 0) || '待生成' },
    {
      label: '候选岗位样本ID',
      value: Array.isArray(report?.target_jobs) && report.target_jobs.length
        ? report.target_jobs.slice(0, 8).map((item: any) => String(item?.job_id || '')).filter(Boolean).join('、')
        : '待生成'
    }
  ]

  const quickPromptBlocks = [
    '请基于当前报告，补全每一阶段的学习资源、项目实践与成果展示方式，保持事实不变。',
    '请把“关键差距”改写成更适合大学生执行的短期提升目标，并给出量化验收标准。',
    '请围绕当前目标方向，补充 2 条可行的转岗路径解释，说明共享技能和额外补课点。'
  ]

  const sectionCheckTag = !hasReport
    ? { color: 'default', text: '未生成' }
    : !hasChecked
      ? { color: 'default', text: '未检查' }
      : issues.length
        ? { color: 'orange', text: `${issues.length} 个问题` }
        : sections.length
          ? { color: 'green', text: '通过' }
          : { color: 'gold', text: '章节为空' }

  return (
    <Space direction="vertical" size={20} style={{ width: '100%' }}>
      {!canWrite ? (
        <Alert type="info" showIcon message="当前账号为只读角色，仅可查看和导出报告，不可生成或编辑。" />
      ) : null}

      {queryReportId ? (
        <Alert
          type="success"
          showIcon
          message="已从顾问会话承接报告"
          description="你可以在这里继续查看结构化摘要、编辑文本稿、进行完整性检查并导出成品。"
        />
      ) : null}
      {!queryReportId && queryTargetJobId ? (
        <Alert
          type="info"
          showIcon
          message="当前来自匹配诊断：按心仪岗位生成报告"
          description={`目标岗位ID：${queryTargetJobId}${queryAutoGenerateJob ? '（已自动触发生成）' : ''}`}
        />
      ) : null}

      <div className="report-hero">
        <div className="report-hero-main">
          <Text className="report-kicker">职业报告中心 · 可编辑 · 可导出 · 可持续完善</Text>
          <Title level={2} className="report-title">职业生涯发展报告工作台</Title>
          <Paragraph className="report-desc">
            把报告生成、结构化诊断、内容润色、完整性检查和成品导出集中在一个工作台里，适合直接演示“方向探索 → 报告输出”的闭环。
          </Paragraph>
          <div className="report-chip-row">
            <Tag color="blue">{selectedStudent ? presentStudentOption(selectedStudent) : '待选学生'}</Tag>
            <Tag color="cyan">{selectedRole ? targetRoleName(selectedRole) : '待选方向'}</Tag>
            {report?.version ? <Tag color="purple">第 {report.version} 版</Tag> : null}
            <Tag color={canWrite ? 'gold' : 'default'}>{canWrite ? '可编辑' : '只读查看'}</Tag>
          </div>
          <div className="report-stat-grid">
            {heroStats.map((item) => (
              <div key={item.label} className={`report-stat-card ${item.tone}`}>
                <div className="report-stat-label">{item.label}</div>
                <div className="report-stat-value">{item.value}<span>{item.suffix}</span></div>
              </div>
            ))}
          </div>
        </div>

        <div className="report-hero-side">
          <Card className="report-action-card" variant="borderless">
            <Space direction="vertical" size={12} style={{ width: '100%' }}>
              <div>
                <Text className="report-side-label">选择学生</Text>
                <Select
                  placeholder="选择学生"
                  options={studentOptions}
                  value={studentId}
                  onChange={setStudentId}
                  showSearch
                  filterOption={false}
                  onSearch={(value) => { void searchStudents(String(value || '').trim()) }}
                />

              </div>
              <div>
                <Text className="report-side-label">选择目标方向</Text>
                <Select
                  placeholder="选择目标方向"
                  options={roleOptions}
                  value={roleId}
                  onChange={setRoleId}
                  showSearch
                  optionFilterProp="label"
                />
              </div>
              <div>
                <Text className="report-side-label">润色风格</Text>
                <Select options={POLISH_STYLE_OPTIONS} value={polishStyle} onChange={setPolishStyle} />
              </div>
              <Space wrap>
                <Button type="primary" icon={<RocketOutlined />} onClick={() => void generateReport()} loading={loading} disabled={!canWrite}>生成报告</Button>
                {queryTargetJobId ? (
                  <Button icon={<RocketOutlined />} onClick={() => void generateReportByTargetJob(queryTargetJobId)} loading={loading} disabled={!canWrite}>
                    按心仪岗位生成
                  </Button>
                ) : null}
                <Button icon={<ReloadOutlined />} onClick={() => void refreshCheck(report?.report_id)} disabled={!report?.report_id}>检查完整性</Button>
                <Button icon={<SyncOutlined />} onClick={() => void polishReport()} loading={loading} disabled={!report?.report_id || !canWrite}>智能润色</Button>
              </Space>
            </Space>
          </Card>
        </div>
      </div>

      <div className="report-workbench">
        <div className="report-left-rail">
          <Card title="报告资产库" extra={<Tag color="blue">{reports.length} 份</Tag>}>
            <div className="report-library-list">
              {reports.length ? reports.map((item: any) => {
                const isActive = item.report_id === report?.report_id
                return (
                  <div key={item.report_id} className={`report-library-item ${isActive ? 'active' : ''}`} onClick={() => void loadReport(item.report_id)}>
                    <div>
                      <div className="report-library-title">{presentReportLabel(item, reports.indexOf(item))}</div>
                      <div className="report-library-meta">更新时间：{formatTimeLabel(item.updated_at)}</div>
                    </div>
                    <Space direction="vertical" size={4} align="end">
                      <Tag color={isActive ? 'green' : 'default'}>第 {item.version || 1} 版</Tag>
                      {isActive ? <Text type="secondary">当前</Text> : null}
                    </Space>
                  </div>
                )
              }) : <Empty description="当前学生还没有报告" image={Empty.PRESENTED_IMAGE_SIMPLE} />}
            </div>
          </Card>

          <Card title="质量与导出" extra={<Tag color={qualityScore >= 80 ? 'green' : qualityScore >= 60 ? 'gold' : 'red'}>{qualityScore} / 100</Tag>}>
            <Space direction="vertical" size={14} style={{ width: '100%' }}>
              <Progress percent={qualityScore} showInfo={false} strokeColor={qualityScore >= 80 ? '#2fd6a7' : qualityScore >= 60 ? '#ffb562' : '#ff6b7a'} />
              <div className="report-quality-row">
                <div>
                  <div className="report-quality-label">章节覆盖</div>
                  <b>{sections.length || 0} / 5</b>
                </div>
                <div>
                  <div className="report-quality-label">问题数</div>
                  <b>{issues.length}</b>
                </div>
                <div>
                  <div className="report-quality-label">导出状态</div>
                  <b>{report?.report_id ? '就绪' : '待生成'}</b>
                </div>
              </div>
              <Space wrap>
                <Button icon={<SaveOutlined />} onClick={() => void saveReport()} disabled={!report?.report_id || !canWrite}>保存</Button>
                <Button icon={<CopyOutlined />} onClick={() => void copyMarkdown()} disabled={!report?.report_id}>复制文本稿</Button>
              </Space>
              <Space wrap>
                {report?.report_id ? <Button icon={<DownloadOutlined />} href={apiUrl(`/reports/${report.report_id}/export?format=pdf`)} target="_blank">导出打印版</Button> : null}
                {report?.report_id ? <Button icon={<FileTextOutlined />} href={apiUrl(`/reports/${report.report_id}/export?format=docx`)} target="_blank">导出可编辑版</Button> : null}
              </Space>
            </Space>
          </Card>
        </div>

        <div className="report-main-column">
          <Card
            title={report ? presentReportLabel(report, reports.findIndex((item: any) => item.report_id === report.report_id)) : '报告驾驶舱'}
            extra={
              <Segmented
                options={[
                  { label: '预览', value: 'preview', icon: <EyeOutlined /> },
                  { label: '编辑', value: 'edit', icon: <EditOutlined /> },
                  { label: '大纲', value: 'outline', icon: <ThunderboltOutlined /> }
                ]}
                value={mode}
                onChange={(value) => setMode(value as any)}
              />
            }
          >
            {report ? (
              <>
                {mode === 'preview' ? (
                  <div className="markdown-preview report-preview"><ReactMarkdown>{markdown}</ReactMarkdown></div>
                ) : null}

                {mode === 'edit' ? (
                  <Input.TextArea value={markdown} onChange={e => setMarkdown(e.target.value)} rows={26} disabled={!canWrite} />
                ) : null}

                {mode === 'outline' ? (
                  <Space direction="vertical" size={16} style={{ width: '100%' }}>
                    <Card size="small" title="摘要与目标">
                      <Paragraph>{report?.summary || '暂无摘要'}</Paragraph>
                      {studentSnapshot?.mbti_type ? (
                        <div className="report-chip-row" style={{ marginBottom: 12 }}>
                          <Tag color="purple">{studentSnapshot.mbti_type}{studentSnapshot?.mbti_label ? ` · ${studentSnapshot.mbti_label}` : ''}</Tag>
                          {(studentSnapshot?.mbti_job_family_hint_labels || []).slice(0, 4).map((item: string) => (
                            <Tag key={item} color="geekblue">{item}</Tag>
                          ))}
                        </div>
                      ) : null}
                      <Descriptions size="small" column={2} bordered>
                        {reportSummaryRows.map((item) => (
                          <Descriptions.Item key={item.label} label={item.label}>{item.value || '-'}</Descriptions.Item>
                        ))}
                      </Descriptions>
                    </Card>

                    <Row gutter={[16, 16]}>
                      <Col span={12}>
                        <Card size="small" title="优势标签">
                          <div className="report-chip-row">
                            {strengths.length ? strengths.map((item: string) => <Tag color="green" key={item}>{item}</Tag>) : <Text type="secondary">暂无优势标签</Text>}
                          </div>
                        </Card>
                      </Col>
                      <Col span={12}>
                        <Card size="small" title="差距标签">
                          <div className="report-chip-row">
                            {gaps.length ? gaps.map((item: string) => <Tag color="orange" key={item}>{item}</Tag>) : <Text type="secondary">暂无差距标签</Text>}
                          </div>
                        </Card>
                      </Col>
                    </Row>

                    <Card size="small" title="行动计划总览">
                      <Timeline
                        items={(actionPlan || []).map((phase: any) => ({
                          color: 'blue',
                          children: (
                            <div>
                              <div className="report-phase-title">{phase.phase} · {phase.duration_weeks || '-'} 周</div>
                              <div className="report-phase-list">
                                {(phase.actions || []).map((action: any) => (
                                  <div key={action.title} className="report-phase-action">
                                    <b>{action.title}</b>：{action.description}
                                  </div>
                                ))}
                              </div>
                            </div>
                          )
                        }))}
                      />
                    </Card>
                  </Space>
                ) : null}
              </>
            ) : (
              <div className="report-empty-state">
                <Title level={4}>还没有载入报告</Title>
                <Text type="secondary">先选择学生与目标方向生成报告，或者从左侧“报告资产库”载入已有成果。</Text>
              </div>
            )}
          </Card>

          <div className="report-main-grid">
            <Card title="匹配维度刻度盘">
              <div className="report-dimension-stack">
                {dimensionRows.length ? dimensionRows.map((item) => (
                  <div key={item.key} className="report-dimension-row">
                    <div className="report-dimension-head">
                      <span>{item.label}</span>
                      <b>{Number.isFinite(item.score) ? item.score.toFixed(1) : '-'}</b>
                    </div>
                    <Progress percent={Math.max(0, Math.min(100, Math.round(item.score || 0)))} showInfo={false} strokeColor="#4da3ff" />
                  </div>
                )) : <Empty description="暂无维度评分" image={Empty.PRESENTED_IMAGE_SIMPLE} />}
              </div>
            </Card>

            <Card title="路径与行动计划快照">
              <Space direction="vertical" size={16} style={{ width: '100%' }}>
                <div>
                  <Text className="report-side-label">垂直路径</Text>
                  <div className="report-chip-row">
                    <PathFlow
                      nodes={verticalPathNodes}
                      nodeLabel={(node: any) => String(node?.title || '').trim() || presentRoleName(node)}
                      emptyText="暂无垂直路径"
                    />
                  </div>
                </div>
                <div>
                  <Text className="report-side-label">转岗建议</Text>
                  <PathFlowList
                    paths={switchPathNodes}
                    nodeLabel={(node: any) => String(node?.title || '').trim() || presentRoleName(node)}
                    emptyText="暂无转岗路径建议"
                    compact
                  />
                </div>
                <div>
                  <Text className="report-side-label">评估与动态调整</Text>
                  <div className="report-evaluation-box">
                    <div>周期：{evaluation?.cycle || '待补充'}</div>
                    <div>指标：{(evaluation?.kpis || []).length || 0} 项</div>
                    <div>调整：{evaluation?.adjustment || '待补充'}</div>
                  </div>
                </div>
              </Space>
            </Card>
          </div>
        </div>

        <div className="report-right-rail">
          <Card title="结构化摘要" extra={<CheckCircleOutlined />}>
            <Descriptions size="small" column={1} bordered>
              <Descriptions.Item label="报告时间">{formatTimeLabel(report?.updated_at || report?.created_at)}</Descriptions.Item>
              <Descriptions.Item label="章节数">{sections.length || 0}</Descriptions.Item>
              <Descriptions.Item label="行动项">{actionItemCount || 0}</Descriptions.Item>
              <Descriptions.Item label="当前模式">{canWrite ? '可编辑工作台' : '只读浏览模式'}</Descriptions.Item>
            </Descriptions>
          </Card>

          <Card title="章节检查" extra={<Tag color={sectionCheckTag.color}>{sectionCheckTag.text}</Tag>}>
            <div className="report-chip-row">
              {!hasReport ? <Text type="secondary">请先生成或载入报告</Text> : sections.length ? sections.map(item => <Tag key={item}>{item}</Tag>) : <Text type="secondary">暂无章节</Text>}
            </div>
            <div className="report-issue-stack">
              {!hasReport ? (
                <Empty description="请先生成或载入报告后再检查" image={Empty.PRESENTED_IMAGE_SIMPLE} />
              ) : !hasChecked ? (
                <Empty description="尚未执行章节检查，请点击“检查完整性”" image={Empty.PRESENTED_IMAGE_SIMPLE} />
              ) : issues.length ? (
                issues.map((issue: any, idx: number) => (
                  <div key={`${issue.type}-${idx}`} className={`report-issue-item ${issue.severity || 'medium'}`}>
                    <div className="report-issue-title">{issue.message || '待补充问题说明'}</div>
                    <div className="report-issue-meta">{presentIssueType(issue.type)} · {presentSeverity(issue.severity)}</div>
                  </div>
                ))
              ) : sections.length ? (
                <Empty description="当前检查未发现明显问题" image={Empty.PRESENTED_IMAGE_SIMPLE} />
              ) : (
                <Alert type="warning" showIcon message="报告正文为空或章节不完整，建议重新生成或补全后再检查。" />
              )}
            </div>
          </Card>

          <Card title="智能续写提示" extra={<Button type="link" size="small" onClick={() => void copyMarkdown()} disabled={!report?.report_id}>复制文本稿</Button>}>
            <Space direction="vertical" size={10} style={{ width: '100%' }}>
              {quickPromptBlocks.map((item) => (
                <div key={item} className="report-prompt-card">{item}</div>
              ))}
              <Text type="secondary">这些提示适合在你接入真实模型后，继续用于补全、润色和迭代。</Text>
            </Space>
          </Card>
        </div>
      </div>
    </Space>
  )
}
