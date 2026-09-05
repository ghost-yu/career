
import React, { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import ReactMarkdown from 'react-markdown'
import { Alert, App, Avatar, Button, Card, Empty, Input, Select, Space, Tag, Typography } from 'antd'
import {
  BranchesOutlined,
  DeleteOutlined,
  FileSearchOutlined,
  FileTextOutlined,
  PlusOutlined,
  RobotOutlined,
  SendOutlined,
  UserOutlined
} from '@ant-design/icons'
import { api } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { PathFlow } from '../components/CareerPathViz'
import { familyLabel } from '../constants/labels'
import { presentJobName, presentRoleName, presentStudentOption } from '../utils/present'

const { Text, Title } = Typography
const { TextArea } = Input

type MsgRole = 'user' | 'assistant'

type Msg = {
  id: string
  role: MsgRole
  content: string
  createdAt: number
  payload?: any
}

type Session = {
  id: string
  backendSessionId?: string
  title: string
  studentId: string
  roleId: string
  roleTitle: string
  jobId: string
  jobTitle: string
  messages: Msg[]
  updatedAt: number
}

const QUICK_PROMPTS = [
  '推荐适合我的职业方向',
  '我更适合前端还是测试方向？',
  '请分析我的优势与短板',
  '请分析当前岗位的能力差距',
  '请基于当前方向生成职业规划报告'
]

function uid(prefix: string) {
  return `${prefix}_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`
}

function shortTime(ts: number) {
  return new Date(ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

function isModelQuestion(text?: string): boolean {
  const raw = String(text || '').trim()
  if (!raw) return false
  const lower = raw.toLowerCase()
  if (lower.includes('what model') || lower.includes('which model') || lower.includes('model')) return true
  return raw.includes('什么模型') || raw.includes('你是什么模型') || raw.includes('当前模型') || raw.includes('大模型')
}

function unwrapPayload(raw: any): any {
  if (!raw || typeof raw !== 'object') return raw
  if (raw.payload && typeof raw.payload === 'object') return raw.payload
  if (raw.result && typeof raw.result === 'object' && !raw.type) return raw.result
  return raw
}

function formatPayloadToText(payload: any, userText?: string): string {
  payload = unwrapPayload(payload)
  if (!payload) return ''
  if (typeof payload === 'string') return payload
  if (isModelQuestion(userText)) {
    const runtime = payload?.agent_runtime || {}
    const provider = String(runtime?.provider || '').trim()
    const model = String(runtime?.model || '').trim()
    if (model || provider) {
      return `当前生涯顾问使用模型：${model || 'unknown'}${provider ? `（provider: ${provider}）` : ''}`
    }
  }
  if (payload?.error) return String(payload.error)
  if (payload?.type === 'role_comparison') return '已完成方向对比，请查看下方详情。'
  if (payload?.type === 'match_result') return '已完成当前岗位能力差距诊断。'
  if (payload?.type === 'profile_review') return '已完成当前画像盘点，请查看下方详情。'
  if (payload?.summary) return String(payload.summary)
  if (payload?.content) return String(payload.content)
  if (payload?.type === 'report') return '职业规划报告已生成，可前往报告中心查看。'
  return '系统已返回结构化结果，请查看下方详情。'
}

function parseAssistant(raw: string): { text: string; payload?: any } {
  const text = String(raw || '').trim()
  if (!text) return { text: '' }
  try {
    const parsed = JSON.parse(text)
    if (parsed && typeof parsed === 'object') {
      const normalized = unwrapPayload(parsed)
      return { text: formatPayloadToText(normalized), payload: normalized }
    }
  } catch {
    // plain text
  }
  return { text }
}

function normalizePathNodes(path: any): any[] {
  if (Array.isArray(path?.nodes)) return path.nodes
  if (Array.isArray(path)) return path
  return []
}

function nodeLabel(node: any): string {
  return presentRoleName(node) || String(node?.title || node?.role_id || '').trim() || '未知节点'
}

function MessageBubble({
  msg,
  canWrite,
  onUseRole,
  onUseJob,
  onAsk,
  onOpenReport
}: {
  msg: Msg
  canWrite: boolean
  onUseRole: (role: any) => void
  onUseJob: (job: any) => void
  onAsk: (text: string, extra?: { roleId?: string; jobId?: string }) => Promise<void>
  onOpenReport: (reportId?: string) => void
}) {
  const payload = unwrapPayload(msg.payload || {})
  const roleItems = Array.isArray(payload?.items) ? payload.items : []

  const renderBody = () => {
    if (msg.role !== 'assistant') {
      return <div style={{ whiteSpace: 'pre-wrap' }}>{msg.content}</div>
    }

    if (payload?.type === 'role_recommendations') {
      if (!roleItems.length) return <Empty description="暂无方向推荐" />
      return (
        <div className="assistant-card-grid">
          {roleItems.slice(0, 6).map((item: any) => (
            <Card key={item.role_id || item.title} size="small" className="assistant-result-card">
              <div className="assistant-result-title">{presentRoleName(item)}</div>
              <div className="assistant-result-meta" style={{ marginTop: 8 }}>
                <Tag color="blue">{familyLabel(item.job_family)}</Tag>
              </div>
              <div className="assistant-result-actions" style={{ marginTop: 10 }}>
                <Button size="small" onClick={() => onUseRole(item)}>设为方向</Button>
                <Button size="small" icon={<BranchesOutlined />} onClick={() => onAsk('请分析当前方向的发展路径', { roleId: item.role_id })} disabled={!canWrite}>看路径</Button>
              </div>
            </Card>
          ))}
        </div>
      )
    }

    if (payload?.type === 'recommendations') {
      if (!roleItems.length) return <Empty description="暂无岗位推荐" />
      return (
        <div className="assistant-card-grid assistant-card-grid-wide">
          {roleItems.slice(0, 8).map((item: any) => (
            <Card key={item.job_id || item.title} size="small" className="assistant-result-card">
              <div className="assistant-result-title">{presentJobName(item)}</div>
              <div className="assistant-result-subtitle">{item.company_name || '未知公司'} · {item.location || '未知地点'}</div>
              <div className="assistant-result-actions" style={{ marginTop: 10 }}>
                <Button size="small" onClick={() => onUseJob(item)}>设为岗位</Button>
                <Button size="small" icon={<FileSearchOutlined />} onClick={() => onAsk('请分析当前岗位的能力差距', { jobId: item.job_id })} disabled={!canWrite}>能力诊断</Button>
              </div>
            </Card>
          ))}
        </div>
      )
    }

    if (payload?.type === 'role_selection') {
      const options = Array.isArray(payload?.options) ? payload.options : []
      if (!options.length) return <Empty description="暂无可供挑选的方向" />
      return (
        <Space direction="vertical" size={10} style={{ width: '100%' }}>
          <Alert type="info" showIcon message={payload?.summary || '已为你筛出可优先考虑的方向'} />
          <div className="assistant-card-grid">
            {options.slice(0, 6).map((item: any) => (
              <Card key={item.role_id || item.title} size="small" className="assistant-result-card">
                <div className="assistant-result-title">{presentRoleName(item)}</div>
                <div className="assistant-result-meta" style={{ marginTop: 8 }}>
                  <Tag color="blue">{familyLabel(item.job_family)}</Tag>
                  {payload?.recommended_role_id && payload.recommended_role_id === item.role_id ? <Tag color="green">优先</Tag> : null}
                </div>
                <div className="assistant-result-actions" style={{ marginTop: 10 }}>
                  <Button size="small" onClick={() => onUseRole(item)}>设为方向</Button>
                  <Button size="small" icon={<BranchesOutlined />} onClick={() => onAsk('请分析当前方向的发展路径', { roleId: item.role_id })} disabled={!canWrite}>看路径</Button>
                </div>
              </Card>
            ))}
          </div>
        </Space>
      )
    }

    if (payload?.type === 'role_comparison') {
      const blocks = Array.isArray(payload?.items) ? payload.items : []
      if (!blocks.length) return <Empty description="暂无可用方向对比结果" />
      return (
        <Space direction="vertical" size={12} style={{ width: '100%' }}>
          <Alert type="info" showIcon message="已完成方向对比" />
          {blocks.map((block: any, idx: number) => {
            const roles = Array.isArray(block?.roles) ? block.roles : []
            return (
              <Card key={`${block?.direction || 'direction'}-${idx}`} size="small" title={`${block?.direction || '待命名方向'}（候选 ${roles.length}）`}>
                {roles.length ? (
                  <div className="assistant-card-grid">
                    {roles.map((item: any) => (
                      <Card key={item.role_id || item.title} size="small" className="assistant-result-card">
                        <div className="assistant-result-title">{presentRoleName(item)}</div>
                        <div className="assistant-result-meta" style={{ marginTop: 8 }}>
                          <Tag color="blue">{familyLabel(item.job_family)}</Tag>
                        </div>
                        <div className="assistant-result-actions" style={{ marginTop: 10 }}>
                          <Button size="small" onClick={() => onUseRole(item)}>设为方向</Button>
                          <Button size="small" icon={<BranchesOutlined />} onClick={() => onAsk('请分析当前方向的发展路径', { roleId: item.role_id })} disabled={!canWrite}>看路径</Button>
                        </div>
                      </Card>
                    ))}
                  </div>
                ) : (
                  <Text type="secondary">该方向暂无可比对的角色样本</Text>
                )}
              </Card>
            )
          })}
        </Space>
      )
    }

    if (payload?.type === 'match_result') {
      const result = payload?.result || {}
      const overallScore = Number(result?.overall_score || 0)
      const dimensions = result?.dimension_scores || {}
      const skills = dimensions?.skills || {}
      const matched = Array.isArray(skills?.matched) ? skills.matched.slice(0, 5) : []
      const missing = Array.isArray(skills?.missing) ? skills.missing.slice(0, 5) : []
      const scoreColor = overallScore >= 75 ? 'green' : overallScore >= 60 ? 'gold' : 'red'
      return (
        <Space direction="vertical" size={12} style={{ width: '100%' }}>
          <Alert type="success" showIcon message="已生成当前岗位能力差距诊断" />
          <Card size="small" title="综合匹配分">
            <Tag color={scoreColor} style={{ fontSize: 14 }}>{Number.isFinite(overallScore) ? overallScore.toFixed(2) : '-'} 分</Tag>
            <div style={{ marginTop: 10, display: 'flex', flexWrap: 'wrap', gap: 8 }}>
              {Object.entries(dimensions).map(([key, value]: [string, any]) => (
                <Tag key={key}>{key}: {Number(value?.score || 0).toFixed(1)}</Tag>
              ))}
            </div>
          </Card>
          <Card size="small" title="优势技能">
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
              {matched.length ? matched.map((item: any, index: number) => (
                <Tag color="green" key={`${item?.skill_id || item?.name || index}`}>{item?.name || item?.skill_id || '未命名技能'}</Tag>
              )) : <Text type="secondary">暂无优势技能</Text>}
            </div>
          </Card>
          <Card size="small" title="关键差距">
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
              {missing.length ? missing.map((item: any, index: number) => (
                <Tag color="orange" key={`${item?.skill_id || item?.name || index}`}>{item?.name || item?.skill_id || '未命名技能'}</Tag>
              )) : <Text type="secondary">暂无关键差距</Text>}
            </div>
          </Card>
        </Space>
      )
    }

    if (payload?.type === 'report') {
      const markdown = String(payload?.markdown || '')
      const preview = markdown.split('\n').filter(Boolean).slice(0, 8).join('\n')
      return (
        <Space direction="vertical" size={12} style={{ width: '100%' }}>
          <Alert type="success" showIcon message="职业规划报告已生成" />
          {preview ? <div className="assistant-report-preview"><ReactMarkdown>{preview}</ReactMarkdown></div> : null}
          <Button type="primary" icon={<FileTextOutlined />} onClick={() => onOpenReport(payload?.report_id)}>进入报告中心</Button>
        </Space>
      )
    }

    if (payload?.type === 'paths' || payload?.type === 'role_paths') {
      const verticalPath = Array.isArray(payload?.vertical_path) ? payload.vertical_path : []
      const switchPaths = Array.isArray(payload?.switch_paths) ? payload.switch_paths : []
      const hasAnyPath = verticalPath.length > 0 || switchPaths.length > 0
      return (
        <Space direction="vertical" size={12} style={{ width: '100%' }}>
          <Alert
            type="info"
            showIcon
            message={payload?.type === 'role_paths' ? '已生成当前方向的发展路径' : '已生成当前岗位的发展路径'}
          />

          <Card size="small" title="晋升路径">
            <PathFlow
              nodes={verticalPath}
              nodeLabel={nodeLabel}
              emptyText="暂无可用晋升路径"
            />
          </Card>

          <Card size="small" title={`转岗路径（${switchPaths.length} 条）`}>
            <Space direction="vertical" size={8} style={{ width: '100%' }}>
              {switchPaths.length ? switchPaths.slice(0, 5).map((path: any, pathIndex: number) => {
                const nodes = normalizePathNodes(path)
                return (
                  <PathFlow
                    key={pathIndex}
                    nodes={nodes}
                    nodeLabel={nodeLabel}
                    compact
                  />
                )
              }) : <Text type="secondary">暂无可用转岗路径</Text>}
            </Space>
          </Card>
          {!hasAnyPath ? (
            <Alert
              type="warning"
              showIcon
              message="当前方向缺少可解释路径，建议先重新推荐方向"
              action={<Button size="small" onClick={() => onAsk('推荐适合我的职业方向')}>重新推荐方向</Button>}
            />
          ) : null}
        </Space>
      )
    }

    return <ReactMarkdown>{msg.content || '...'}</ReactMarkdown>
  }

  return (
    <div className={`assistant-msg assistant-msg-${msg.role}`}>
      <div className={`assistant-message-line ${msg.role === 'user' ? 'is-user' : 'is-assistant'}`}>
        {msg.role !== 'user' ? <Avatar className="assistant-avatar assistant-avatar-ai" size={38} icon={<RobotOutlined />} /> : null}
        <div className="assistant-msg-main">
          <div className="assistant-msg-role">
            {msg.role === 'user' ? <UserOutlined /> : <RobotOutlined />}
            <span>{msg.role === 'user' ? '我' : '生涯顾问'}</span>
            <span className="assistant-msg-time">{shortTime(msg.createdAt)}</span>
          </div>
          <div className="assistant-msg-content">{renderBody()}</div>
        </div>
        {msg.role === 'user' ? <Avatar className="assistant-avatar assistant-avatar-user" size={38} icon={<UserOutlined />} /> : null}
      </div>
    </div>
  )
}
export default function Assistant() {
  const { message } = App.useApp()
  const { user, canWrite } = useAuth()
  const navigate = useNavigate()

  const [defaultStudentId, setDefaultStudentId] = useState('')
  const [studentOptions, setStudentOptions] = useState<{ label: string; value: string }[]>([])
  const [sessions, setSessions] = useState<Session[]>([])
  const [activeId, setActiveId] = useState('')
  const [input, setInput] = useState('推荐适合我的职业方向')
  const [sending, setSending] = useState(false)
  const [deletingSessionId, setDeletingSessionId] = useState('')
  const [clearingMessages, setClearingMessages] = useState(false)
  const bottomRef = useRef<HTMLDivElement | null>(null)
  const sessionsRef = useRef<Session[]>([])

  const makeFreshSession = (studentId?: string): Session => ({
    id: uid('session'),
    title: '新会话',
    studentId: String(studentId || defaultStudentId || ''),
    roleId: '',
    roleTitle: '',
    jobId: '',
    jobTitle: '',
    messages: [],
    updatedAt: Date.now()
  })

  const activeSession = useMemo(() => sessions.find((s) => s.id === activeId) || null, [sessions, activeId])

  useEffect(() => {
    if (!activeId && sessions.length) setActiveId(sessions[0].id)
  }, [sessions, activeId])

  useEffect(() => {
    sessionsRef.current = sessions
  }, [sessions])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [activeSession?.messages])

  const updateSessionById = (sessionId: string, updater: (s: Session) => Session) => {
    setSessions((prev) => prev.map((s) => (s.id === sessionId ? updater(s) : s)))
  }

  const loadServerMessages = async (localId: string, backendSessionId: string) => {
    try {
      const res = await api.get(`/chat/sessions/${backendSessionId}/messages`, { params: { limit: 200, offset: 0 } })
      const items = Array.isArray(res.data?.items) ? res.data.items : []
      const msgs: Msg[] = items.map((it: any) => {
        if (it.role === 'assistant') {
          const parsed = parseAssistant(it.content || '')
          return {
            id: it.message_id || uid('a'),
            role: 'assistant',
            content: parsed.text,
            payload: parsed.payload,
            createdAt: Date.parse(it.created_at || '') || Date.now()
          }
        }
        return {
          id: it.message_id || uid('u'),
          role: 'user',
          content: String(it.content || ''),
          createdAt: Date.parse(it.created_at || '') || Date.now()
        }
      })
      updateSessionById(localId, (s) => ({ ...s, messages: msgs, updatedAt: Date.now() }))
    } catch {
      // ignore
    }
  }

  const loadStudentOptions = async (keyword: string = '') => {
    const students = await api.get('/students', {
      params: { limit: 200, offset: 0, q: keyword || undefined }
    })
    const studentItems = Array.isArray(students.data?.items) ? students.data.items : []
    setStudentOptions(studentItems.map((item: any, index: number) => ({ label: presentStudentOption(item, index), value: item.student_id })))
    return studentItems
  }

  useEffect(() => {
    if (!user?.user_id) return

    const bootstrap = async () => {
      try {
        const studentItems = await loadStudentOptions()
        const firstStudent = String(studentItems[0]?.student_id || '')
        setDefaultStudentId(firstStudent)
        const list = firstStudent
          ? (() => {
            // Query server history for the initial selected student.
            return api.get('/chat/sessions', { params: { limit: 30, offset: 0, student_id: firstStudent } })
          })()
          : Promise.resolve({ data: { items: [] } })
        const ss = await list
        const sessionItems = Array.isArray(ss.data?.items) ? ss.data.items : []
        const mapped: Session[] = sessionItems.map((it: any) => ({
          id: uid('session'),
          backendSessionId: it.session_id,
          title: it.title || '历史会话',
          studentId: it.student_id || firstStudent,
          roleId: '',
          roleTitle: '',
          jobId: it.last_job_id || '',
          jobTitle: '',
          messages: [],
          updatedAt: Date.parse(it.updated_at || '') || Date.now()
        }))

        const fresh = makeFreshSession(firstStudent)
        setSessions([fresh, ...mapped])
        setActiveId(fresh.id)
      } catch {
        const fallback: Session = makeFreshSession('')
        setSessions([fallback])
        setActiveId(fallback.id)
      }
    }

    void bootstrap()
  }, [user?.user_id])

  const createSession = () => {
    const one: Session = makeFreshSession(activeSession?.studentId || defaultStudentId)
    setSessions((prev) => [one, ...prev])
    setActiveId(one.id)
    setInput('')
  }

  const removeSessionLocal = (id: string) => {
    setSessions((prev) => {
      const next = prev.filter((s) => s.id !== id)
      if (!next.length) {
        const one: Session = makeFreshSession(defaultStudentId)
        setActiveId(one.id)
        return [one]
      }
      if (activeId === id) setActiveId(next[0].id)
      return next
    })
  }

  const removeSession = async (id: string) => {
    const target = sessions.find((s) => s.id === id)
    if (!target) return
    if (target.backendSessionId) {
      setDeletingSessionId(id)
      try {
        await api.delete(`/chat/sessions/${target.backendSessionId}`)
      } catch (e: any) {
        message.error(`删除失败：${e?.response?.data?.detail || e?.message || '请求失败'}`)
        return
      } finally {
        setDeletingSessionId('')
      }
    }
    removeSessionLocal(id)
    message.success('会话已删除')
  }

  const handleStudentChange = (value: string) => {
    const nextStudentId = String(value || '').trim()
    if (!nextStudentId || !activeId) return
    const current = sessionsRef.current.find((s) => s.id === activeId) || activeSession
    if (!current) return
    if (current.studentId === nextStudentId) return

    if (current.backendSessionId || current.messages.length) {
      const one = makeFreshSession(nextStudentId)
      setSessions((prev) => [one, ...prev])
      setActiveId(one.id)
      setInput('')
      message.info('已为该学生创建新会话，避免混入历史上下文。')
      return
    }

    updateSessionById(activeId, (s) => ({
      ...s,
      studentId: nextStudentId,
      roleId: '',
      roleTitle: '',
      jobId: '',
      jobTitle: '',
      updatedAt: Date.now()
    }))
  }

  const resolveDefaultJobForRole = async (roleId: string): Promise<{ jobId: string; jobTitle: string }> => {
    try {
      const roleRes = await api.get(`/roles/${roleId}`)
      const memberJobs = Array.isArray(roleRes?.data?.member_jobs) ? roleRes.data.member_jobs : []
      const primaryJob = memberJobs.find((item: any) => String(item?.job_id || '').trim())
      if (primaryJob) {
        return {
          jobId: String(primaryJob.job_id),
          jobTitle: presentJobName(primaryJob)
        }
      }

      const members = Array.isArray(roleRes?.data?.members) ? roleRes.data.members : []
      const firstJobId = String(members[0] || '').trim()
      if (!firstJobId) return { jobId: '', jobTitle: '' }
      try {
        const jobRes = await api.get(`/jobs/${firstJobId}`)
        const job = jobRes?.data?.job
        if (job && String(job?.job_id || '').trim()) {
          return { jobId: String(job.job_id), jobTitle: presentJobName(job) }
        }
      } catch {
        // ignore fetch detail failure, keep fallback id
      }
      return { jobId: firstJobId, jobTitle: firstJobId }
    } catch {
      return { jobId: '', jobTitle: '' }
    }
  }

  const applyRole = async (role: any) => {
    if (!activeId) return
    const roleId = String(role?.role_id || '').trim()
    if (!roleId) return
    const roleTitle = presentRoleName(role)
    const { jobId, jobTitle } = await resolveDefaultJobForRole(roleId)
    const roleTip = jobId
      ? `已设为当前方向：${roleTitle}，并自动绑定岗位：${jobTitle}。你可以继续点击“看路径”，或直接问我“请分析当前岗位的能力差距”。`
      : `已设为当前方向：${roleTitle}。你可以继续点击“看路径”，或直接问我“这个方向的能力差距是什么？”`
    const note: Msg = {
      id: uid('a'),
      role: 'assistant',
      content: roleTip,
      createdAt: Date.now()
    }
    updateSessionById(activeId, (s) => ({
      ...s,
      roleId,
      roleTitle,
      jobId: jobId || '',
      jobTitle: jobId ? jobTitle : '',
      messages: [...s.messages, note],
      updatedAt: Date.now()
    }))
    message.success(jobId ? `已设为方向：${roleTitle}（已绑定岗位）` : `已设为方向：${roleTitle}`)
  }

  const applyJob = (job: any) => {
    if (!activeId) return
    const jobId = String(job?.job_id || '').trim()
    if (!jobId) return
    const jobTitle = presentJobName(job)
    const note: Msg = {
      id: uid('a'),
      role: 'assistant',
      content: `已设为当前岗位：${jobTitle}。你可以继续点击“能力诊断”，或让我直接给出匹配改进建议。`,
      createdAt: Date.now()
    }
    updateSessionById(activeId, (s) => ({ ...s, jobId, jobTitle, messages: [...s.messages, note], updatedAt: Date.now() }))
    message.success(`已设为岗位：${jobTitle}`)
  }

  const openReport = (reportId?: string) => {
    if (!activeSession) return
    const params = new URLSearchParams()
    params.set('student_id', activeSession.studentId)
    if (reportId) params.set('report_id', reportId)
    navigate(`/report?${params.toString()}`)
  }
  const sendMessage = async (text: string, extra?: { roleId?: string; jobId?: string }) => {
    if (!activeSession || !text.trim()) return
    if (!String(activeSession.studentId || '').trim()) {
      message.warning('请先选择学生，再开始咨询。')
      return
    }
    if (sending) {
      message.info('上一条消息还在处理中，请稍候。')
      return
    }
    if (!canWrite) {
      message.warning('当前账号为只读模式，不能发送新消息。')
      return
    }

    const sessionId = activeSession.id
    const content = text.trim()
    const userMsg: Msg = { id: uid('u'), role: 'user', content, createdAt: Date.now() }
    setInput('')
    setSending(true)

    updateSessionById(sessionId, (s) => ({
      ...s,
      title: s.messages.length ? s.title : content.slice(0, 18),
      messages: [...s.messages, userMsg],
      updatedAt: Date.now()
    }))

    try {
      const current = sessionsRef.current.find((s) => s.id === sessionId) || activeSession
      const res = await api.post('/chat/agent', {
        student_id: current.studentId,
        message: content,
        role_id: extra?.roleId || current.roleId || undefined,
        job_id: extra?.jobId || current.jobId || undefined,
        session_id: current.backendSessionId || undefined
      })
      const payload = unwrapPayload(res.data)

      const assistantMsg: Msg = {
        id: uid('a'),
        role: 'assistant',
        content: formatPayloadToText(payload, content),
        payload,
        createdAt: Date.now()
      }

      updateSessionById(sessionId, (s) => ({
        ...s,
        backendSessionId: res.data?.session_id || s.backendSessionId,
        messages: [...s.messages, assistantMsg],
        updatedAt: Date.now()
      }))
    } catch (e: any) {
      const status = Number(e?.response?.status || 0)
      if (status === 403) {
        message.error('当前账号没有执行权限。')
      } else {
        message.error(`发送失败：${e?.response?.data?.detail || e?.message || '请求失败'}`)
      }
      updateSessionById(sessionId, (s) => ({
        ...s,
        messages: [...s.messages, { id: uid('a'), role: 'assistant', content: '当前请求未成功，请稍后重试。', createdAt: Date.now() }],
        updatedAt: Date.now()
      }))
    } finally {
      setSending(false)
    }
  }

  const clearActiveMessages = async () => {
    if (!activeId) return
    const target = sessions.find((s) => s.id === activeId)
    if (!target) return
    if (target.backendSessionId) {
      setClearingMessages(true)
      try {
        await api.delete(`/chat/sessions/${target.backendSessionId}/messages`)
      } catch (e: any) {
        message.error(`清空失败：${e?.response?.data?.detail || e?.message || '请求失败'}`)
        return
      } finally {
        setClearingMessages(false)
      }
    }
    updateSessionById(activeId, (s) => ({ ...s, messages: [], updatedAt: Date.now() }))
    message.success('当前会话已清空')
  }

  return (
    <div className="advisor-layout">
      <div className="advisor-side">
        <Card title="咨询会话" extra={<Button type="primary" size="small" icon={<PlusOutlined />} onClick={createSession}>新建</Button>} styles={{ body: { padding: 10 } }}>
          <div className="assistant-session-list">
            {sessions.map((s) => (
              <div
                key={s.id}
                className={`assistant-session-item ${s.id === activeId ? 'active' : ''}`}
                onClick={() => {
                  setActiveId(s.id)
                  if (s.backendSessionId && !s.messages.length) {
                    void loadServerMessages(s.id, s.backendSessionId)
                  }
                }}
              >
                <div>
                  <div className="assistant-session-title">{s.title || '新会话'}</div>
                  <div className="assistant-session-meta">最近更新 · {shortTime(s.updatedAt)}</div>
                </div>
                <Button
                  size="small"
                  type="text"
                  danger
                  icon={<DeleteOutlined />}
                  loading={deletingSessionId === s.id}
                  onClick={(e) => { e.stopPropagation(); void removeSession(s.id) }}
                />
              </div>
            ))}
          </div>
        </Card>

        <Card title="当前对象">
          <Space direction="vertical" size={14} style={{ width: '100%' }}>
            <div>
              <Text type="secondary">选择学生</Text>
              <Select
                style={{ width: '100%', marginTop: 8 }}
                value={activeSession?.studentId || undefined}
                options={studentOptions}
                onChange={handleStudentChange}
                showSearch
                filterOption={false}
                onSearch={(value) => { void loadStudentOptions(String(value || '').trim()) }}
              />
            </div>
            <div>
              <Text type="secondary">当前方向</Text>
              <div className="dashboard-tag-row" style={{ marginTop: 8 }}>
                {activeSession?.roleTitle ? <Tag color="blue">{activeSession.roleTitle}</Tag> : <Text type="secondary">暂未选定</Text>}
              </div>
            </div>
            <div>
              <Text type="secondary">当前岗位</Text>
              <div className="dashboard-tag-row" style={{ marginTop: 8 }}>
                {activeSession?.jobTitle ? <Tag color="green">{activeSession.jobTitle}</Tag> : <Text type="secondary">暂未选定</Text>}
              </div>
            </div>
          </Space>
        </Card>
      </div>

      <div className="advisor-main">
        <Card>
          <div className="assistant-header assistant-header-rich">
            <div>
              <Title level={4} style={{ margin: 0 }}>生涯顾问</Title>
            </div>
            <Space>
              <Tag>{activeSession?.messages.length || 0} 条消息</Tag>
              <Tag color={sending ? 'processing' : 'blue'}>{sending ? '思考中' : '可咨询'}</Tag>
            </Space>
          </div>

          {!canWrite ? <Alert showIcon type="info" style={{ marginBottom: 12 }} message="当前账号为只读展示模式，可查看历史会话，不能发起新咨询。" /> : null}

          <div className="assistant-prompt-strip">
            {QUICK_PROMPTS.map((item) => (
              <Button key={item} onClick={() => setInput(item)}>{item}</Button>
            ))}
          </div>

          <div className="assistant-chat-window advisor-chat-window">
            {(activeSession?.messages || []).map((msg) => (
              <MessageBubble key={msg.id} msg={msg} canWrite={canWrite} onUseRole={applyRole} onUseJob={applyJob} onAsk={sendMessage} onOpenReport={openReport} />
            ))}
            {!(activeSession?.messages || []).length ? (
              <div className="assistant-empty">
                <div className="assistant-empty-title">从一个具体问题开始</div>
              </div>
            ) : null}
            <div ref={bottomRef} />
          </div>

          <div className="assistant-input-wrap">
            <TextArea
              value={input}
              autoSize={{ minRows: 2, maxRows: 6 }}
              onChange={(e) => setInput(e.target.value)}
              onPressEnter={(e) => {
                if (!e.shiftKey) {
                  e.preventDefault()
                  void sendMessage(input)
                }
              }}
              placeholder="输入你的职业问题，Enter 发送，Shift+Enter 换行"
              disabled={!canWrite}
            />
            <div className="assistant-input-actions">
              <Button onClick={() => void clearActiveMessages()} loading={clearingMessages}>清空当前展示</Button>
              <Button type="primary" icon={<SendOutlined />} loading={sending} onClick={() => void sendMessage(input)} disabled={!canWrite}>发送</Button>
            </div>
          </div>
        </Card>
      </div>
    </div>
  )
}
