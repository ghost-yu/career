import React, { useEffect, useMemo, useState } from 'react'
import { Alert, Button, Progress, Space, Tag, Typography } from 'antd'
import { ArrowLeftOutlined, ReloadOutlined } from '@ant-design/icons'
import { api } from '../api/client'
import { formatMonthlySalary, formatNumber } from '../utils/format'

const { Text, Title } = Typography

const KB_REQUIREMENT_LABELS: Record<string, string> = {
  kb_root_accessible: '知识库目录可访问',
  kb_docs_at_least_20: '知识文档量>=20',
  kb_generated_docs_present: '生成文档已产出',
  kb_vector_index_present: '向量索引文件已生成',
  kb_vector_index_loadable: '向量索引可加载',
  kb_search_available: '知识检索可用',
  kb_ready_for_match_report: '支持匹配/报告链路',
}

type RingItem = {
  name: string
  value: number
  color: string
}

const RING_COLORS = ['#3dc6ff', '#40f5bf', '#ffcf6f', '#ff8fa3', '#8aa0ff', '#c792ff', '#5ae0ff']

function buildRingBackground(items: RingItem[]) {
  const total = items.reduce((acc, item) => acc + Math.max(0, Number(item.value || 0)), 0)
  if (!total) return 'conic-gradient(#2a3550 0 100%)'
  let cursor = 0
  const stops = items.map((item) => {
    const start = (cursor / total) * 100
    cursor += Math.max(0, Number(item.value || 0))
    const end = (cursor / total) * 100
    return `${item.color} ${start}% ${end}%`
  })
  return `conic-gradient(${stops.join(', ')})`
}

function RingChart({ title, items }: { title: string; items: RingItem[] }) {
  const total = items.reduce((acc, item) => acc + Math.max(0, Number(item.value || 0)), 0)
  return (
    <div className="defense-panel">
      <div className="defense-panel-title-row">
        <Title level={5} className="defense-panel-title">{title}</Title>
        <Text className="defense-panel-subtitle">总计 {formatNumber(total)}</Text>
      </div>
      <div className="defense-ring-wrap">
        <div className="defense-ring" style={{ background: buildRingBackground(items) }}>
          <div className="defense-ring-core">
            <div className="defense-ring-total">{formatNumber(total)}</div>
            <div className="defense-ring-label">样本数</div>
          </div>
        </div>
        <div className="defense-legend-list">
          {items.map((item) => {
            const ratio = total ? Math.round((item.value / total) * 1000) / 10 : 0
            return (
              <div className="defense-legend-row" key={`${title}-${item.name}`}>
                <span className="defense-legend-dot" style={{ background: item.color }} />
                <span className="defense-legend-name">{item.name}</span>
                <span className="defense-legend-value">{formatNumber(item.value)} / {ratio}%</span>
              </div>
            )
          })}
          {!items.length ? <Text type="secondary">暂无可视化数据</Text> : null}
        </div>
      </div>
    </div>
  )
}

export default function DefenseScreen() {
  const [overview, setOverview] = useState<any>(null)
  const [readiness, setReadiness] = useState<any>(null)
  const [jobs, setJobs] = useState<any[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [now, setNow] = useState(() => new Date())

  const load = async () => {
    setLoading(true)
    setError('')
    try {
      const [overviewRes, readinessRes, jobsRes] = await Promise.all([
        api.get('/insights/overview'),
        api.get('/insights/kb/readiness'),
        api.get('/jobs', { params: { limit: 10, offset: 0 } })
      ])
      setOverview(overviewRes.data || null)
      setReadiness(readinessRes.data || null)
      setJobs(jobsRes.data?.items || [])
    } catch (e: any) {
      setError(e?.response?.data?.detail || e?.message || '大屏数据加载失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load()
  }, [])

  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), 1000)
    return () => window.clearInterval(timer)
  }, [])

  const counts = overview?.counts || {}
  const readinessPairs = Object.entries(readiness?.requirements || {})
  const readinessPercent = readinessPairs.length
    ? Math.round((readinessPairs.filter(([, value]) => Boolean(value)).length / readinessPairs.length) * 100)
    : 0

  const heroCards = [
    { label: '岗位样本', value: Number(counts.jobs || 0), hint: '就业市场样本池' },
    { label: '职业角色', value: Number(counts.roles || 0), hint: '路径规划节点' },
    { label: '学生画像', value: Number(counts.student_profiles || 0), hint: '已建模档案数' },
    { label: '生涯报告', value: Number(counts.reports || 0), hint: '可交付报告数' }
  ]

  const cityRows = (overview?.top_cities || []).slice(0, 8)
  const industryRows = (overview?.top_industries || []).slice(0, 8)
  const familyRows = (overview?.top_job_families || []).slice(0, 8)
  const hardSkills = (overview?.top_hard_skills || []).slice(0, 16)

  const cityMax = Math.max(1, ...cityRows.map((item: any) => Number(item.count || 0)))
  const industryMax = Math.max(1, ...industryRows.map((item: any) => Number(item.count || 0)))
  const familyMax = Math.max(1, ...familyRows.map((item: any) => Number(item.count || 0)))

  const salaryRing = useMemo<RingItem[]>(() => {
    const source = (overview?.salary_bands || []).slice(0, 7)
    return source.map((item: any, index: number) => ({
      name: String(item.name || `薪资段${index + 1}`),
      value: Number(item.count || 0),
      color: RING_COLORS[index % RING_COLORS.length]
    })).filter((item) => item.value > 0)
  }, [overview])

  const eduRing = useMemo<RingItem[]>(() => {
    const bucket: Record<string, number> = {}
    for (const job of jobs) {
      const key = String(job.education || '不限')
      bucket[key] = (bucket[key] || 0) + 1
    }
    const rows = Object.entries(bucket)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 7)
      .map(([name, value], index) => ({ name, value, color: RING_COLORS[index % RING_COLORS.length] }))
    return rows
  }, [jobs])

  return (
    <div className="defense-screen">
      <div className="defense-overlay" />
      <header className="defense-header">
        <div>
          <Text className="defense-kicker">实时运营看板</Text>
          <Title level={2} className="defense-title">职业规划数据中心</Title>
        </div>
        <Space>
          <Tag className="defense-clock">{now.toLocaleString('zh-CN')}</Tag>
          <Button icon={<ReloadOutlined />} onClick={() => void load()} loading={loading}>刷新</Button>
          <Button icon={<ArrowLeftOutlined />} onClick={() => window.location.assign('/')}>返回系统</Button>
        </Space>
      </header>

      {error ? (
        <Alert
          type="error"
          showIcon
          className="defense-alert"
          message="看板加载失败"
          description={error}
          action={<Button size="small" onClick={() => void load()}>重试</Button>}
        />
      ) : null}

      <section className="defense-kpi-grid">
        {heroCards.map((item) => (
          <article className="defense-kpi-card" key={item.label}>
            <div className="defense-kpi-label">{item.label}</div>
            <div className="defense-kpi-value">{formatNumber(item.value)}</div>
            <div className="defense-kpi-hint">{item.hint}</div>
          </article>
        ))}
      </section>

      <section className="defense-layout">
        <div className="defense-col">
          <div className="defense-panel">
            <div className="defense-panel-title-row">
              <Title level={5} className="defense-panel-title">知识库准备度</Title>
              <Text className="defense-panel-subtitle">基于知识库检索链路关键能力</Text>
            </div>
            <div className="defense-readiness">
              <Progress
                type="dashboard"
                percent={readinessPercent}
                strokeColor={{ '0%': '#39b8ff', '100%': '#2cffd2' }}
                trailColor="#1b2740"
                format={(value) => `${value}%`}
              />
              <div className="defense-readiness-list">
                {readinessPairs.slice(0, 8).map(([key, value]) => (
                  <div className="defense-state-row" key={key}>
                    <span>{KB_REQUIREMENT_LABELS[key] || key}</span>
                    <Tag color={value ? 'success' : 'warning'}>{value ? '已就绪' : '待完善'}</Tag>
                  </div>
                ))}
              </div>
            </div>
          </div>

          <div className="defense-panel">
            <div className="defense-panel-title-row">
              <Title level={5} className="defense-panel-title">热门城市</Title>
              <Text className="defense-panel-subtitle">岗位分布</Text>
            </div>
            <div className="defense-bars">
              {cityRows.map((item: any) => {
                const count = Number(item.count || 0)
                const ratio = Math.max(6, Math.round((count / cityMax) * 100))
                return (
                  <div className="defense-bar-row" key={item.name}>
                    <div className="defense-bar-label">{item.name}</div>
                    <div className="defense-bar-track"><div className="defense-bar-fill" style={{ width: `${ratio}%` }} /></div>
                    <div className="defense-bar-value">{formatNumber(count)}</div>
                  </div>
                )
              })}
              {!cityRows.length ? <Text type="secondary">暂无城市数据</Text> : null}
            </div>
          </div>

          <div className="defense-panel">
            <div className="defense-panel-title-row">
              <Title level={5} className="defense-panel-title">重点行业</Title>
              <Text className="defense-panel-subtitle">市场方向</Text>
            </div>
            <div className="defense-bars">
              {industryRows.map((item: any) => {
                const count = Number(item.count || 0)
                const ratio = Math.max(6, Math.round((count / industryMax) * 100))
                return (
                  <div className="defense-bar-row" key={item.name}>
                    <div className="defense-bar-label">{item.name}</div>
                    <div className="defense-bar-track"><div className="defense-bar-fill alt" style={{ width: `${ratio}%` }} /></div>
                    <div className="defense-bar-value">{formatNumber(count)}</div>
                  </div>
                )
              })}
              {!industryRows.length ? <Text type="secondary">暂无行业数据</Text> : null}
            </div>
          </div>
        </div>

        <div className="defense-col defense-col-main">
          <div className="defense-panel">
            <div className="defense-panel-title-row">
              <Title level={5} className="defense-panel-title">岗位族群热度</Title>
              <Text className="defense-panel-subtitle">核心方向分布</Text>
            </div>
            <div className="defense-bars">
              {familyRows.map((item: any) => {
                const count = Number(item.count || 0)
                const ratio = Math.max(8, Math.round((count / familyMax) * 100))
                return (
                  <div className="defense-bar-row" key={item.name}>
                    <div className="defense-bar-label">{item.label || item.name}</div>
                    <div className="defense-bar-track"><div className="defense-bar-fill cyan" style={{ width: `${ratio}%` }} /></div>
                    <div className="defense-bar-value">{formatNumber(count)}</div>
                  </div>
                )
              })}
              {!familyRows.length ? <Text type="secondary">暂无岗位族群数据</Text> : null}
            </div>
          </div>

          <div className="defense-panel">
            <div className="defense-panel-title-row">
              <Title level={5} className="defense-panel-title">关键词热区</Title>
              <Text className="defense-panel-subtitle">岗位高频技能词</Text>
            </div>
            <div className="defense-skill-cloud">
              {hardSkills.map((item: any, index: number) => (
                <Tag key={`${item.name}-${index}`} className={`defense-skill-tag tone-${index % 5}`}>{item.name}</Tag>
              ))}
              {!hardSkills.length ? <Text type="secondary">暂无关键词数据</Text> : null}
            </div>
          </div>

          <div className="defense-panel">
            <div className="defense-panel-title-row">
              <Title level={5} className="defense-panel-title">岗位样本 TOP10</Title>
              <Text className="defense-panel-subtitle">最新样本</Text>
            </div>
            <div className="defense-table-wrap">
              <table className="defense-table">
                <thead>
                  <tr>
                    <th>岗位</th>
                    <th>公司</th>
                    <th>城市</th>
                    <th>薪资</th>
                  </tr>
                </thead>
                <tbody>
                  {jobs.map((job: any) => (
                    <tr key={job.job_id}>
                      <td>{job.title || '-'}</td>
                      <td>{job.company_name || '-'}</td>
                      <td>{job.location || '-'}</td>
                      <td>{formatMonthlySalary(job.salary_min, job.salary_max, job.salary_period)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {!jobs.length ? <Text type="secondary">暂无岗位样本数据</Text> : null}
            </div>
          </div>
        </div>

        <div className="defense-col">
          <RingChart title="薪资结构分布" items={salaryRing} />
          <RingChart title="学历需求分布（样本）" items={eduRing} />
        </div>
      </section>
    </div>
  )
}
