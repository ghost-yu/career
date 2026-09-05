import React, { useEffect, useMemo, useState } from 'react'
import { Alert, Button, Card, Empty, List, Progress, Space, Tag, Typography } from 'antd'
import {
  AppstoreOutlined,
  ClusterOutlined,
  ExpandOutlined,
  FileTextOutlined,
  ReloadOutlined,
  UserOutlined
} from '@ant-design/icons'
import { api } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { PathFlow } from '../components/CareerPathViz'
import { familyLabel, levelLabel } from '../constants/labels'
import { formatMonthlySalary, formatNumber } from '../utils/format'
import { presentEventSource, presentEventType, presentRoleName } from '../utils/present'

const { Title, Text } = Typography

const STRATEGY_LABELS: Record<string, string> = {
  balanced: '均衡',
  skill_first: '技能优先',
  location_first: '地点优先',
  salary_first: '薪资优先',
  unspecified: '未标记'
}

export default function Dashboard() {
  const { isAdmin } = useAuth()
  const [summary, setSummary] = useState<any>(null)
  const [overview, setOverview] = useState<any>(null)
  const [eventSummary, setEventSummary] = useState<any>(null)
  const [recentJobs, setRecentJobs] = useState<any[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const load = async () => {
    setLoading(true)
    setError('')
    try {
      const [overviewRes, readinessRes, jobsRes] = await Promise.all([
        api.get('/insights/overview'),
        api.get('/insights/competition/readiness'),
        api.get('/jobs', { params: { limit: 8, offset: 0 } })
      ])
      setOverview(overviewRes.data || null)
      setRecentJobs(jobsRes.data?.items || [])

      if (isAdmin) {
        const [summaryRes, eventRes] = await Promise.all([
          api.get('/admin/summary'),
          api.get('/admin/events/summary', { params: { days: 14, limit: 8 } })
        ])
        setSummary(summaryRes.data || null)
        setEventSummary(eventRes.data || null)
      } else {
        setSummary({
          counts: overviewRes.data?.counts || {},
          readiness: readinessRes.data || {},
          recent_jobs: jobsRes.data?.items || []
        })
        setEventSummary(null)
      }
    } catch (e: any) {
      setError(e?.response?.data?.detail || e?.message || '加载失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load()
  }, [isAdmin])

  const readiness = summary?.readiness || {}

  const heroStats = useMemo(() => ([
    { label: '岗位总量', value: summary?.counts?.jobs || 0, icon: <AppstoreOutlined /> },
    { label: '角色总量', value: summary?.counts?.roles || 0, icon: <ClusterOutlined /> },
    { label: '学生画像', value: summary?.counts?.student_profiles || 0, icon: <UserOutlined /> },
    { label: '报告数量', value: summary?.counts?.reports || 0, icon: <FileTextOutlined /> }
  ]), [summary])

  const topFamilies = useMemo(() => (overview?.top_job_families || []).slice(0, 8), [overview])
  const topCities = useMemo(() => (overview?.top_cities || []).slice(0, 8), [overview])
  const topIndustries = useMemo(() => (overview?.top_industries || []).slice(0, 10), [overview])
  const topSkills = useMemo(() => (overview?.top_hard_skills || []).slice(0, 18), [overview])
  const salaryBands = useMemo(() => (overview?.salary_bands || []).slice(0, 8), [overview])
  const salaryTotal = useMemo(
    () => salaryBands.reduce((sum: number, item: any) => sum + Number(item?.count || 0), 0),
    [salaryBands]
  )
  const topSalary = salaryBands[0] || null
  const maxKpiValue = useMemo(() => Math.max(...heroStats.map((item) => Number(item.value || 0)), 1), [heroStats])
  const maxFamilyCount = useMemo(
    () => Math.max(...topFamilies.map((item: any) => Number(item?.count || 0)), 1),
    [topFamilies]
  )
  const maxCityCount = useMemo(
    () => Math.max(...topCities.map((item: any) => Number(item?.count || 0)), 1),
    [topCities]
  )

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }} className="dashboard-pro adminv2-dashboard">
      {error ? (
        <Alert
          type="error"
          showIcon
          message="首页加载失败"
          description={String(error)}
          action={<Button size="small" icon={<ReloadOutlined />} onClick={() => void load()}>重试</Button>}
        />
      ) : null}

      <div className="adminv2-banner">
        <div className="adminv2-banner-main">
          <Text className="adminv2-kicker">DASHBOARD</Text>
          <Title level={2} className="adminv2-title">运营大屏工作台</Title>
          <div className="adminv2-tag-row">
            {topFamilies.slice(0, 6).map((item: any) => (
              <Tag key={item.name} color="blue">{item.label || item.name} {item.count}</Tag>
            ))}
          </div>
          <Space style={{ marginTop: 14 }} wrap className="adminv2-banner-actions">
            <Button
              type="primary"
              icon={<ExpandOutlined />}
              onClick={() => window.open('/defense-screen', '_blank', 'noopener,noreferrer')}
            >
              打开大屏
            </Button>
            <Button icon={<ReloadOutlined />} onClick={() => void load()} loading={loading}>刷新数据</Button>
          </Space>
        </div>
      </div>

      <div className="adminv2-kpi-grid">
        {heroStats.map((item) => {
          const value = Number(item.value || 0)
          const ratio = Math.max(6, Math.round((value / maxKpiValue) * 100))
          return (
            <Card key={item.label} className="adminv2-kpi-card" loading={loading}>
              <div className="adminv2-kpi-head">
                <div className="adminv2-kpi-icon">{item.icon}</div>
                <Tag color="default">实时</Tag>
              </div>
              <Text className="adminv2-kpi-label">{item.label}</Text>
              <div className="adminv2-kpi-value">{formatNumber(value)}</div>
              <div className="adminv2-mini-track">
                <span className="adminv2-mini-fill" style={{ width: `${ratio}%` }} />
              </div>
            </Card>
          )
        })}
      </div>

      <Card className="adminv2-board-card" loading={loading}>
        <div className="adminv2-board-header">
          <div>
            <Text strong>业务分布看板</Text>
          </div>
          <Tag color="processing">LIVE</Tag>
        </div>
        <div className="adminv2-board-grid">
          <div className="adminv2-board-main">
            <Text className="adminv2-section-title">岗位族群热度</Text>
            <div className="adminv2-rank-list">
              {topFamilies.length ? topFamilies.map((item: any, idx: number) => {
                const count = Number(item.count || 0)
                const pct = Math.max(8, Math.round((count / maxFamilyCount) * 100))
                return (
                  <div className="adminv2-rank-row" key={item.name || idx}>
                    <div className="adminv2-rank-name">{idx + 1}. {item.label || item.name}</div>
                    <div className="adminv2-rank-bar">
                      <span className="adminv2-rank-fill" style={{ width: `${pct}%` }} />
                    </div>
                    <div className="adminv2-rank-count">{formatNumber(count)}</div>
                  </div>
                )
              }) : <Empty description="暂无数据" />}
            </div>
          </div>
          <div className="adminv2-board-side">
            <Text className="adminv2-section-title">城市排名 TOP</Text>
            <div className="adminv2-rank-list">
              {topCities.length ? topCities.map((item: any, idx: number) => {
                const count = Number(item.count || 0)
                const pct = Math.max(10, Math.round((count / maxCityCount) * 100))
                return (
                  <div className="adminv2-rank-row" key={item.name || idx}>
                    <div className="adminv2-rank-name">{idx + 1}. {item.name}</div>
                    <div className="adminv2-rank-bar">
                      <span className="adminv2-rank-fill adminv2-rank-fill-city" style={{ width: `${pct}%` }} />
                    </div>
                    <div className="adminv2-rank-count">{formatNumber(count)}</div>
                  </div>
                )
              }) : <Empty description="暂无数据" />}
            </div>
          </div>
        </div>
      </Card>

      <div className="adminv2-grid adminv2-grid-2">
        <Card title="市场标签" loading={loading} className="adminv2-card">
          <div className="adminv2-stack">
            <section>
              <Text className="adminv2-section-title">热门行业</Text>
              <div className="adminv2-tag-row">
                {topIndustries.map((item: any) => <Tag color="cyan" key={item.name}>{item.name} {item.count}</Tag>)}
              </div>
            </section>
            <section>
              <Text className="adminv2-section-title">高频技能</Text>
              <div className="adminv2-tag-row">
                {topSkills.map((item: any, idx: number) => <Tag color="geekblue" key={`${item.name}-${idx}`}>{item.name}</Tag>)}
              </div>
            </section>
            <section>
              <Text className="adminv2-section-title">重点城市</Text>
              <div className="adminv2-tag-row">
                {topCities.map((item: any) => <Tag key={item.name}>{item.name} {item.count}</Tag>)}
              </div>
            </section>
          </div>
        </Card>

        <Card title="薪资水平分布" loading={loading} className="adminv2-card">
          <div className="adminv2-stack">
            <div className="adminv2-ready-inline">
              <div>
                <div className="adminv2-inline-value">{topSalary ? String(topSalary.name || '未知') : '未知'}</div>
                <div className="adminv2-inline-label">主流薪资带</div>
              </div>
              <Tag color="blue">
                样本 {formatNumber(salaryTotal)}
              </Tag>
            </div>
            <Progress
              percent={salaryTotal > 0 && topSalary ? Math.round((Number(topSalary.count || 0) / salaryTotal) * 100) : 0}
              showInfo={false}
              strokeColor="#1677ff"
            />
            <div className="adminv2-requirement-list">
              {salaryBands.length ? salaryBands.map((item: any) => {
                const count = Number(item?.count || 0)
                const pct = salaryTotal > 0 ? Math.round((count / salaryTotal) * 100) : 0
                return (
                  <div key={item?.name} className="adminv2-requirement-item">
                    <Text strong>{String(item?.name || '未知')}</Text>
                    <Tag color="cyan">{formatNumber(count)}（{pct}%）</Tag>
                  </div>
                )
              }) : (
                <Empty description="暂无薪资数据" />
              )}
            </div>
          </div>
        </Card>
      </div>

      <div className="adminv2-grid adminv2-grid-2">
        <Card title="最新岗位" loading={loading} className="adminv2-card">
          <List
            dataSource={recentJobs}
            locale={{ emptyText: <Empty description="暂无岗位" /> }}
            renderItem={(job: any) => (
              <List.Item className="adminv2-job-item">
                <List.Item.Meta
                  title={<span>{job.title}</span>}
                  description={`${job.company_name || '未知公司'} · ${job.location || '未知地点'} · ${job.industry || '未知行业'}`}
                />
                <Text>{formatMonthlySalary(job.salary_min, job.salary_max, job.salary_period)}</Text>
              </List.Item>
            )}
          />
        </Card>

        <Card title="路径样例" loading={loading} className="adminv2-card">
          <div className="adminv2-stack">
            {(readiness?.sample_switch_roles || []).slice(0, 4).map((item: any) => (
              <div key={item.role_id} className="adminv2-path-card">
                <Text strong>{presentRoleName(item)}</Text>
                {(item.paths || []).slice(0, 2).map((path: any[], idx: number) => (
                  <div key={idx} className="adminv2-path-line">
                    <PathFlow
                      nodes={path || []}
                      nodeLabel={(node: any) => String(node?.title || '').trim() || presentRoleName(node)}
                      compact
                    />
                  </div>
                ))}
              </div>
            ))}
            {!(readiness?.sample_switch_roles || []).length ? <Empty description="暂无样例" /> : null}
          </div>
        </Card>
      </div>

      <div className="adminv2-grid adminv2-grid-2">
        <Card title="角色分布" loading={loading} className="adminv2-card">
          <div className="adminv2-role-list">
            {(summary?.recent_roles || []).slice(0, 8).map((role: any) => (
              <div key={role.role_id} className="adminv2-role-item">
                <div>
                  <Text strong>{presentRoleName(role)}</Text>
                  <div className="adminv2-role-meta">{familyLabel(role.job_family)} · {levelLabel(role.level_label)}</div>
                </div>
                <Tag color="blue">方向</Tag>
              </div>
            ))}
            {!(summary?.recent_roles || []).length ? <Empty description="暂无数据" /> : null}
          </div>
        </Card>

        <Card title="近 14 天" loading={loading} className="adminv2-card">
          {isAdmin ? (
            <div className="adminv2-stack">
              <section>
                <Text className="adminv2-section-title">事件类型</Text>
                <div className="adminv2-tag-row">
                  {(eventSummary?.counts_by_type_recent || []).map((item: any) => (
                    <Tag key={item.event_type}>{presentEventType(item.event_type)}: {item.count}</Tag>
                  ))}
                </div>
              </section>
              <section>
                <Text className="adminv2-section-title">来源分布</Text>
                <div className="adminv2-tag-row">
                  {(eventSummary?.counts_by_source_recent || []).map((item: any) => (
                    <Tag color="cyan" key={item.source}>{presentEventSource(item.source)}: {item.count}</Tag>
                  ))}
                </div>
              </section>
              <section>
                <Text className="adminv2-section-title">策略使用</Text>
                <div className="adminv2-tag-row">
                  {(eventSummary?.strategy_usage_recent || []).map((item: any) => (
                    <Tag color="purple" key={item.strategy}>{STRATEGY_LABELS[item.strategy] || item.strategy} · {item.count}</Tag>
                  ))}
                </div>
              </section>
            </div>
          ) : (
            <Alert type="info" showIcon message="当前账号不显示管理事件统计" />
          )}
        </Card>
      </div>
    </Space>
  )
}
