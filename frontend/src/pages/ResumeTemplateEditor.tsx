import React, { useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
  Alert,
  App,
  Button,
  Card,
  Col,
  Empty,
  Input,
  Row,
  Select,
  Space,
  Tag,
  Typography
} from 'antd'
import {
  CopyOutlined,
  FilePdfOutlined,
  DeleteOutlined,
  PlusOutlined,
  PrinterOutlined,
  SaveOutlined
} from '@ant-design/icons'
import ReactMarkdown from 'react-markdown'
import { loadResumeTemplateDraft, type ResumeTemplateDraft } from '../utils/resumeTemplateDraft'

const { Text, Title } = Typography

type EditableSection = {
  id: string
  title: string
  content: string
}

type TemplateStyle = 'classic' | 'modern' | 'minimal'

const TEMPLATE_STYLE_OPTIONS = [
  { label: '经典模板', value: 'classic' },
  { label: '现代模板', value: 'modern' },
  { label: '简约模板', value: 'minimal' }
]

const ACCENT_OPTIONS = [
  { label: '深海蓝', value: '#1f4c9a' },
  { label: '青松绿', value: '#1c7f5f' },
  { label: '炭黑灰', value: '#374151' },
  { label: '赭石橙', value: '#b45309' }
]

function makeId(prefix: string) {
  return `${prefix}_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`
}

function parseMarkdownToSections(markdown: string): { name: string; sections: EditableSection[] } {
  const lines = String(markdown || '').replace(/\r\n/g, '\n').split('\n')
  let name = ''
  const sections: EditableSection[] = []
  let currentTitle = ''
  let currentLines: string[] = []

  const pushCurrent = () => {
    const content = currentLines.join('\n').trim()
    if (!currentTitle && !content) return
    sections.push({
      id: makeId('sec'),
      title: currentTitle || '内容',
      content
    })
  }

  for (const raw of lines) {
    const line = raw.trimEnd()
    if (!name && /^#\s+/.test(line)) {
      name = line.replace(/^#\s+/, '').trim()
      continue
    }
    if (/^##\s+/.test(line)) {
      pushCurrent()
      currentTitle = line.replace(/^##\s+/, '').trim()
      currentLines = []
      continue
    }
    if (/^#\s+/.test(line)) {
      continue
    }
    currentLines.push(raw)
  }
  pushCurrent()

  if (!sections.length && String(markdown || '').trim()) {
    sections.push({
      id: makeId('sec'),
      title: '经历与能力',
      content: String(markdown || '').trim()
    })
  }

  return { name, sections }
}

function pickSummary(targetedSummary: string, sections: EditableSection[]): string {
  const direct = String(targetedSummary || '').trim()
  if (direct) return direct
  const found = sections.find(item => /(summary|概述|简介|自我评价)/i.test(item.title))
  if (found) return found.content.slice(0, 260).trim()
  return ''
}

function renderMarkdownContent(content: string) {
  const text = String(content || '').replace(/\r\n/g, '\n').replace(/\n{3,}/g, '\n\n').trim()
  if (!text) {
    return <p className="resume-template-empty">暂无内容</p>
  }
  return (
    <ReactMarkdown
      className="resume-template-markdown"
      components={{
        h1: ({ children }) => <h3>{children}</h3>,
        h2: ({ children }) => <h3>{children}</h3>,
        h3: ({ children }) => <h4>{children}</h4>,
      }}
    >
      {text}
    </ReactMarkdown>
  )
}

function buildMarkdown(name: string, targetTitle: string, summary: string, sections: EditableSection[]) {
  const lines: string[] = []
  lines.push(`# ${name || 'Candidate'}`)
  if (targetTitle) {
    lines.push(`## Target Role`)
    lines.push(targetTitle)
  }
  if (summary) {
    lines.push(`## Professional Summary`)
    lines.push(summary)
  }
  sections.forEach(section => {
    lines.push(`## ${section.title || 'Section'}`)
    lines.push(section.content || '')
  })
  return lines.join('\n\n').trim()
}

export default function ResumeTemplateEditor() {
  const { message } = App.useApp()
  const [searchParams] = useSearchParams()
  const draftKey = String(searchParams.get('draft') || '')

  const [draft, setDraft] = useState<ResumeTemplateDraft | null>(null)
  const [name, setName] = useState('')
  const [targetTitle, setTargetTitle] = useState('')
  const [summary, setSummary] = useState('')
  const [sections, setSections] = useState<EditableSection[]>([])
  const [coverLetter, setCoverLetter] = useState('')
  const [templateStyle, setTemplateStyle] = useState<TemplateStyle>('classic')
  const [accentColor, setAccentColor] = useState('#1f4c9a')

  useEffect(() => {
    if (!draftKey) return
    const loaded = loadResumeTemplateDraft(draftKey)
    setDraft(loaded)
    if (!loaded) return
    const parsed = parseMarkdownToSections(loaded.resume_markdown || '')
    setName(parsed.name || '')
    setTargetTitle(String(loaded.target_title || ''))
    setSummary(pickSummary(String(loaded.targeted_summary || ''), parsed.sections))
    setSections(parsed.sections)
    setCoverLetter(String(loaded.cover_letter || ''))
  }, [draftKey])

  const resumeMarkdown = useMemo(
    () => buildMarkdown(name, targetTitle, summary, sections),
    [name, targetTitle, summary, sections]
  )

  const addSection = () => {
    setSections(prev => [...prev, { id: makeId('sec'), title: '新章节', content: '' }])
  }

  const removeSection = (id: string) => {
    setSections(prev => prev.filter(item => item.id !== id))
  }

  const updateSectionTitle = (id: string, nextTitle: string) => {
    setSections(prev => prev.map(item => (item.id === id ? { ...item, title: nextTitle } : item)))
  }

  const updateSectionContent = (id: string, nextContent: string) => {
    setSections(prev => prev.map(item => (item.id === id ? { ...item, content: nextContent } : item)))
  }

  const saveDraft = () => {
    if (!draftKey || !draft) return
    const nextDraft: ResumeTemplateDraft = {
      ...draft,
      target_title: targetTitle,
      resume_markdown: resumeMarkdown,
      cover_letter: coverLetter,
      targeted_summary: summary
    }
    window.localStorage.setItem(draftKey, JSON.stringify(nextDraft))
    setDraft(nextDraft)
    message.success('模板草稿已保存到本地')
  }

  const copyResumeMarkdown = async () => {
    try {
      await navigator.clipboard.writeText(resumeMarkdown)
      message.success('已复制简历 Markdown')
    } catch {
      message.warning('复制失败，请手动复制')
    }
  }

  const copyCoverLetter = async () => {
    try {
      await navigator.clipboard.writeText(coverLetter)
      message.success('已复制推荐信')
    } catch {
      message.warning('复制失败，请手动复制')
    }
  }

  const printResume = () => {
    window.print()
  }

  const exportPdf = () => {
    message.info('即将打开打印窗口，请在打印机选项中选择“另存为 PDF”。')
    window.print()
  }

  if (!draftKey || !draft) {
    return (
      <div className="resume-template-page">
        <Card>
          <Alert
            type="warning"
            showIcon
            message="未找到可编辑草稿"
            description="请先在 简历报告生成 里生成结果，再点击“弹出模板编辑器”。"
          />
          <div style={{ marginTop: 16 }}>
            <Empty description="没有可加载的模板数据" />
          </div>
        </Card>
      </div>
    )
  }

  return (
    <div className="resume-template-page">
      <Card className="resume-template-toolbar-card">
        <Space wrap size={10} style={{ width: '100%', justifyContent: 'space-between' }}>
          <Space wrap size={10}>
            <Tag color="blue">学生：{draft.student_id || '-'}</Tag>
            <Tag color="cyan">岗位：{draft.target_title || '-'}</Tag>
            <Tag color={draft.llm_used ? 'green' : 'default'}>{draft.llm_used ? 'LLM已调用' : '未调用LLM'}</Tag>
          </Space>
          <Space wrap size={8}>
            <Button icon={<CopyOutlined />} onClick={() => void copyResumeMarkdown()}>复制简历Markdown</Button>
            <Button icon={<CopyOutlined />} onClick={() => void copyCoverLetter()}>复制推荐信</Button>
            <Button icon={<SaveOutlined />} type="primary" onClick={saveDraft}>保存草稿</Button>
            <Button icon={<FilePdfOutlined />} onClick={exportPdf}>导出PDF</Button>
            <Button icon={<PrinterOutlined />} onClick={printResume}>打印</Button>
          </Space>
        </Space>
      </Card>

      <Row gutter={[16, 16]}>
        <Col xs={24} xl={10} className="resume-template-editor-col">
          <Card title="模板编辑面板">
            <Space direction="vertical" size={12} style={{ width: '100%' }}>
              <div>
                <Text type="secondary">模板样式</Text>
                <Select
                  style={{ width: '100%', marginTop: 6 }}
                  value={templateStyle}
                  options={TEMPLATE_STYLE_OPTIONS}
                  onChange={value => setTemplateStyle(value as TemplateStyle)}
                />
              </div>

              <div>
                <Text type="secondary">主色</Text>
                <Select
                  style={{ width: '100%', marginTop: 6 }}
                  value={accentColor}
                  options={ACCENT_OPTIONS}
                  onChange={value => setAccentColor(String(value || '#1f4c9a'))}
                />
              </div>

              <div>
                <Text type="secondary">姓名</Text>
                <Input style={{ marginTop: 6 }} value={name} onChange={e => setName(e.target.value)} />
              </div>

              <div>
                <Text type="secondary">目标岗位</Text>
                <Input style={{ marginTop: 6 }} value={targetTitle} onChange={e => setTargetTitle(e.target.value)} />
              </div>

              <div>
                <Text type="secondary">职业摘要</Text>
                <Input.TextArea
                  rows={4}
                  style={{ marginTop: 6 }}
                  value={summary}
                  onChange={e => setSummary(e.target.value)}
                />
              </div>

              <div className="resume-template-sections">
                <Space align="center" style={{ width: '100%', justifyContent: 'space-between' }}>
                  <Text strong>章节编辑</Text>
                  <Button size="small" icon={<PlusOutlined />} onClick={addSection}>新增章节</Button>
                </Space>

                {sections.map(section => (
                  <Card key={section.id} size="small" className="resume-template-section-card">
                    <Space direction="vertical" size={8} style={{ width: '100%' }}>
                      <Space style={{ width: '100%', justifyContent: 'space-between' }}>
                        <Text type="secondary">章节标题</Text>
                        <Button
                          danger
                          size="small"
                          icon={<DeleteOutlined />}
                          onClick={() => removeSection(section.id)}
                        >
                          删除
                        </Button>
                      </Space>
                      <Input value={section.title} onChange={e => updateSectionTitle(section.id, e.target.value)} />
                      <Input.TextArea
                        rows={5}
                        value={section.content}
                        onChange={e => updateSectionContent(section.id, e.target.value)}
                        placeholder="支持 Markdown，例如 ## 标题、- 列表、**加粗**"
                      />
                    </Space>
                  </Card>
                ))}
              </div>

              <div>
                <Text type="secondary">推荐信（可编辑）</Text>
                <Input.TextArea
                  rows={8}
                  style={{ marginTop: 6 }}
                  value={coverLetter}
                  onChange={e => setCoverLetter(e.target.value)}
                />
              </div>
            </Space>
          </Card>
        </Col>

        <Col xs={24} xl={14} className="resume-template-preview-col">
          <Card title="排版预览" className="resume-template-preview-card">
            <div
              className={`resume-template-paper resume-template-${templateStyle}`}
              style={{ ['--resume-accent' as any]: accentColor }}
            >
              <header className="resume-template-header">
                <h1>{name || '候选人姓名'}</h1>
                <p>{targetTitle || '目标岗位'}</p>
              </header>

              {summary ? (
                <section className="resume-template-summary">
                  <h2>职业摘要</h2>
                  {renderMarkdownContent(summary)}
                </section>
              ) : null}

              {sections.map(section => (
                <section className="resume-template-section" key={section.id}>
                  <h2>{section.title || '章节'}</h2>
                  <div className="resume-template-content">
                    {renderMarkdownContent(section.content)}
                  </div>
                </section>
              ))}

              <section className="resume-template-section">
                <h2>推荐信</h2>
                <div className="resume-template-cover-letter">
                  {renderMarkdownContent(coverLetter)}
                </div>
              </section>
            </div>
          </Card>
        </Col>
      </Row>
    </div>
  )
}
