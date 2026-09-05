import React, { useEffect, useMemo, useState } from 'react'
import {
  Alert,
  Button,
  Card,
  Col,
  Drawer,
  Empty,
  Input,
  Progress,
  Row,
  Select,
  Space,
  Table,
  Tag,
  Typography
} from 'antd'
import {
  FireOutlined,
  GlobalOutlined,
  RadarChartOutlined,
  RiseOutlined,
  SearchOutlined,
  TeamOutlined
} from '@ant-design/icons'
import { api } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { PathFlow } from '../components/CareerPathViz'
import { familyLabel, familyOptions, levelLabel } from '../constants/labels'
import { presentRoleName, presentStudentOption } from '../utils/present'
import { formatCurrency, formatNumber } from '../utils/format'

const { Title, Text, Paragraph } = Typography

const strategyOptions = [
  { label: '均衡', value: 'balanced' },
  { label: '技能优先', value: 'skill_first' },
  { label: '地点优先', value: 'location_first' },
  { label: '薪资优先', value: 'salary_first' }
]

function SkillTags({ items }: { items: any[] }) {
  return (
    <Space size={[0, 8]} wrap>
      {(items || []).map(item => <Tag key={item.skill_id || item.name}>{item.name || item.skill_id}</Tag>)}
    </Space>
  )
}

function normalizeProfileTags(items: any[] | undefined, keys: string[]) {
  const out: any[] = []
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
    out.push({ name })
  }
  return out
}

function percentOf(total: number, count: number) {
  if (!total) return 0
  return Math.max(0, Math.min(100, Math.round((count / total) * 100)))
}

export default function Jobs() {
  const { canWrite } = useAuth()
  const [items, setItems] = useState<any[]>([])
  const [kbRefs, setKbRefs] = useState<any[]>([])
  const [behaviorEventsUsed, setBehaviorEventsUsed] = useState(0)
  const [loading, setLoading] = useState(false)
  const [metaError, setMetaError] = useState('')
  const [listError, setListError] = useState('')
  const [keyword, setKeyword] = useState('')
  const [jobFamily, setJobFamily] = useState('')
  const [strategy, setStrategy] = useState('balanced')
  const [students, setStudents] = useState<any[]>([])
  const [studentId, setStudentId] = useState<string>('')
  const [activeRole, setActiveRole] = useState<any>(null)
  const [detail, setDetail] = useState<any>(null)
  const [jobDetail, setJobDetail] = useState<any>(null)
  const [jobDetailLoading, setJobDetailLoading] = useState(false)
  const [jobDetailFromRole, setJobDetailFromRole] = useState(false)
  const [overview, setOverview] = useState<any>(null)
  const [readiness, setReadiness] = useState<any>(null)

  useEffect(() => {
    const loadMeta = async () => {
      try {
        setMetaError('')
        const [studentsRes, overviewRes, readinessRes] = await Promise.all([
          api.get('/students', { params: { limit: 200, offset: 0 } }),
          api.get('/insights/overview'),
          api.get('/insights/competition/readiness')
        ])
        setStudents(studentsRes.data.items || [])
        setOverview(overviewRes.data)
        setReadiness(readinessRes.data)
      } catch (e: any) {
        setMetaError(String(e?.response?.data?.detail || e?.message || '岗位看板基础数据加载失败'))
      }
    }
    void loadMeta()
  }, [])

  const searchStudents = async (keyword: string = '') => {
    try {
      const res = await api.get('/students', {
        params: { limit: 200, offset: 0, q: keyword || undefined }
      })
      setStudents(Array.isArray(res.data?.items) ? res.data.items : [])
    } catch {
      // ignore search errors to avoid interrupting current view
    }
  }

  const load = async () => {
    setLoading(true)
    setListError('')
    try {
      if (studentId && canWrite) {
        const res = await api.post('/match/recommend_roles', {
          student_id: studentId,
          strategy,
          top_k: 30,
          job_family: jobFamily || undefined,
          q: keyword || undefined
        })
        setItems(res.data.items || [])
        setKbRefs(Array.isArray(res.data?.kb_references) ? res.data.kb_references : [])
        setBehaviorEventsUsed(Number(res.data?.behavior_used_events || 0))
        void api.post('/match/events', {
          student_id: studentId,
          event_type: 'SEARCH',
          source: 'jobs_page',
          meta: { mode: 'personalized', strategy, jobFamily, keyword }
        }).catch(() => undefined)
      } else {
        const res = await api.get('/insights/role_samples', { params: { top_k: 30, job_family: jobFamily || undefined } })
        let rows = res.data.items || []
        if (keyword.trim()) {
          const kw = keyword.trim().toLowerCase()
          rows = rows.filter((row: any) => `${row.title_rep || ''} ${row.base_role || ''}`.toLowerCase().includes(kw))
        }
        setItems(rows)
        setKbRefs([])
        setBehaviorEventsUsed(0)
      }
    } catch (e: any) {
      setListError(String(e?.response?.data?.detail || e?.message || '角色工作台加载失败'))
      setItems([])
      setKbRefs([])
      setBehaviorEventsUsed(0)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load()
  }, [jobFamily, strategy, studentId, canWrite])

  const fetchRoleDetail = async (roleId: string, row: any) => {
    const res = await api.get(`/roles/${roleId}`)
    setActiveRole(row)
    setDetail(res.data)
    if (studentId && canWrite) {
      void api.post('/match/events', {
        student_id: studentId,
        event_type: 'VIEW_ROLE',
        role_id: roleId,
        job_id: row?.representative_job_id,
        source: 'jobs_page',
        meta: { mode: 'personalized', strategy, jobFamily, keyword }
      }).catch(() => undefined)
    }
  }

  const openJobProfile = async (jobId: string, fromRoleDrawer: boolean = false) => {
    const id = String(jobId || '').trim()
    if (!id) return
    setJobDetailFromRole(fromRoleDrawer)
    setJobDetail({ job: { job_id: id } })
    setJobDetailLoading(true)
    try {
      const res = await api.get(`/jobs/${id}`)
      setJobDetail(res.data || { job: { job_id: id } })
    } catch (e: any) {
      setJobDetail({ job: { job_id: id }, error: String(e?.response?.data?.detail || e?.message || '岗位画像加载失败') })
    } finally {
      setJobDetailLoading(false)
    }
  }

  const closeJobDetail = () => {
    setJobDetail(null)
    setJobDetailLoading(false)
    setJobDetailFromRole(false)
  }

  const renderJobDetailContent = () => {
    if (!jobDetail) return null
    return (
      <Space direction="vertical" size={16} style={{ width: '100%' }}>
        {jobDetailLoading ? <Text type="secondary">岗位画像加载中...</Text> : null}
        {jobDetail?.error ? <Alert type="warning" showIcon message="岗位画像加载失败" description={String(jobDetail.error)} /> : null}
        <Card size="small" title="岗位基础信息">
          <Row gutter={[12, 12]}>
            <Col span={12}><Text strong>岗位ID：</Text><Text>{jobDetail?.job?.job_id || '-'}</Text></Col>
            <Col span={12}><Text strong>岗位名称：</Text><Text>{jobDetail?.job?.title || '-'}</Text></Col>
            <Col span={12}><Text strong>公司：</Text><Text>{jobDetail?.job?.company_name || '-'}</Text></Col>
            <Col span={12}><Text strong>地点：</Text><Text>{jobDetail?.job?.location || '-'}</Text></Col>
            <Col span={12}><Text strong>薪资：</Text><Text>{formatCurrency(jobDetail?.job?.salary_min)} - {formatCurrency(jobDetail?.job?.salary_max)}</Text></Col>
          </Row>
        </Card>

        {jobDetail?.profile?.profile ? (
          <Card size="small" title="岗位画像">
            <Space direction="vertical" size={12} style={{ width: '100%' }}>
              <div>
                <Text strong>岗位族：</Text>
                <Tag style={{ marginLeft: 8 }}>{jobDetail?.profile?.profile?.job_family_label || familyLabel(jobDetail?.profile?.profile?.job_family)}</Tag>
              </div>
              <div>
                <Text strong>硬技能：</Text>
                <div style={{ marginTop: 8 }}>
                  <SkillTags items={normalizeProfileTags(jobDetail?.profile?.profile?.hard_skills, ['mention', 'name', 'skill_id'])} />
                </div>
              </div>
              <div>
                <Text strong>软技能：</Text>
                <div style={{ marginTop: 8 }}>
                  <SkillTags items={normalizeProfileTags(jobDetail?.profile?.profile?.soft_skills, ['name', 'mention', 'soft_skill_id'])} />
                </div>
              </div>
              <div>
                <Text strong>建议证书：</Text>
                <div style={{ marginTop: 8 }}>
                  <SkillTags items={normalizeProfileTags(jobDetail?.profile?.profile?.certificates, ['name', 'certificate_id'])} />
                </div>
              </div>
              <div>
                <Text strong>学历要求：</Text>
                <Text style={{ marginLeft: 8 }}>{jobDetail?.profile?.profile?.basic_requirements?.education || '-'}</Text>
              </div>
              <div>
                <Text strong>经验要求：</Text>
                <Text style={{ marginLeft: 8 }}>
                  {jobDetail?.profile?.profile?.basic_requirements?.experience_years_min === null || jobDetail?.profile?.profile?.basic_requirements?.experience_years_min === undefined
                    ? '-'
                    : `${jobDetail?.profile?.profile?.basic_requirements?.experience_years_min} 年+`}
                </Text>
              </div>
              <div>
                <Text strong>标签：</Text>
                <div style={{ marginTop: 8 }}>
                  <SkillTags items={normalizeProfileTags(jobDetail?.profile?.profile?.tags, ['name'])} />
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
    )
  }

  const columns = useMemo(() => [
    {
      title: '岗位角色',
      dataIndex: 'title_rep',
      render: (_: any, row: any) => (
        <Button type="link" onClick={() => void fetchRoleDetail(row.role_id, row)}>
          {presentRoleName(row)}
        </Button>
      )
    },
    {
      title: '岗位族 / 层级',
      dataIndex: 'job_family',
      render: (_v: string, row: any) => (
        <Space>
          <Tag color="blue">{row.job_family_label || familyLabel(row.job_family)}</Tag>
          <Tag>{row.level_label_zh || levelLabel(row.level_label)}</Tag>
        </Space>
      )
    },
    {
      title: '综合得分',
      render: (_: any, row: any) => (
        <Space>
          {typeof row.overall_score === 'number' ? <Tag color="green">综合 {Math.round(row.overall_score)}</Tag> : <Tag>样本观察</Tag>}
          {typeof row.rank_score === 'number' ? <Tag>排序 {Math.round(row.rank_score)}</Tag> : null}
        </Space>
      )
    },
    {
      title: '样本规模',
      dataIndex: 'member_count',
      render: (v: number) => <Tag color={v >= 50 ? 'green' : v >= 20 ? 'blue' : 'default'}>{v || 0}</Tag>
    },
    {
      title: '薪资区间',
      render: (_: any, row: any) => {
        const stats = row.salary_stats || {}
        return `${formatCurrency(stats.salary_min_avg)} - ${formatCurrency(stats.salary_max_avg)}`
      }
    },
    {
      title: '高频能力',
      dataIndex: 'top_hard_skills',
      render: (v: any[]) => <SkillTags items={(v || []).slice(0, 4)} />
    },
    {
      title: '转岗弹性',
      dataIndex: 'switch_path_count',
      render: (v: number) => <Tag color={v >= 2 ? 'purple' : 'orange'}>{v || 0} 条</Tag>
    }
  ], [studentId, strategy, jobFamily, keyword])

  const heroMetrics = useMemo(() => {
    const counts = overview?.counts || {}
    const readinessMetrics = readiness?.metrics || {}
    return [
      { label: '岗位资产', value: counts.jobs || 0, icon: <GlobalOutlined /> },
      { label: '职业角色', value: counts.roles || 0, icon: <RadarChartOutlined /> },
      { label: '晋升链路', value: readinessMetrics.roles_with_vertical_paths || 0, icon: <RiseOutlined /> },
      { label: '转岗角色', value: readinessMetrics.roles_with_switch_paths || 0, icon: <FireOutlined /> }
    ]
  }, [overview, readiness])

  const familyCards = useMemo(() => (overview?.top_job_families || []).slice(0, 8), [overview])
  const salaryBands = useMemo(() => overview?.salary_bands || [], [overview])
  const topCities = useMemo(() => overview?.top_cities || [], [overview])
  const topIndustries = useMemo(() => overview?.top_industries || [], [overview])
  const topHardSkills = useMemo(() => overview?.top_hard_skills || [], [overview])
  const topCompanyTypes = useMemo(() => overview?.top_company_types || [], [overview])
  const topCompanySizes = useMemo(() => overview?.top_company_sizes || [], [overview])
  const totalJobs = Number(overview?.counts?.jobs || 0)
  const marketPulse = useMemo(() => {
    const roleCount = items.length
    const avgMembers = roleCount ? Math.round(items.reduce((acc: number, item: any) => acc + Number(item?.member_count || 0), 0) / roleCount) : 0
    const strongSwitch = items.filter((item: any) => Number(item?.switch_path_count || 0) >= 2).length
    const avgScore = roleCount ? Math.round(items.reduce((acc: number, item: any) => acc + Number(item?.overall_score || 0), 0) / roleCount) : 0
    return { roleCount, avgMembers, strongSwitch, avgScore }
  }, [items])

  return (
    <Space direction="vertical" size={20} style={{ width: '100%' }}>
      {!canWrite ? (
        <Alert type="info" showIcon message="只读模式下已禁用个性化写入能力，当前展示公开市场洞察结果。" />
      ) : null}
      {metaError ? <Alert type="warning" showIcon message="岗位页基础数据异常" description={metaError} /> : null}
      {listError ? <Alert type="warning" showIcon message="岗位角色工作台加载异常" description={listError} /> : null}

      <div className="market-hero">
        <div className="market-hero-main">
          <Text className="market-kicker">岗位洞察 · 市场快照 · 角色簇 · 能力热区</Text>
          <Title level={2} className="market-title">就业市场与岗位角色驾驶舱</Title>
          <Paragraph className="market-desc">
            参考招聘控制台的“顶部总览 + 数据概览 + 角色工作台”布局，把岗位样本、方向分群、薪资结构和能力需求集中展示，便于评委快速理解平台的岗位侧能力。
          </Paragraph>
          <div className="market-chip-row">
            {familyCards.slice(0, 6).map((item: any) => (
              <Tag key={item.name} color="blue" onClick={() => setJobFamily(item.name)}>
                {item.label || item.name} {item.count}
              </Tag>
            ))}
          </div>
          <div className="market-stat-grid">
            {heroMetrics.map(item => (
              <div key={item.label} className="market-stat-card">
                <div className="market-stat-icon">{item.icon}</div>
                <div>
                  <div className="market-stat-label">{item.label}</div>
                  <div className="market-stat-value">{formatNumber(item.value)}</div>
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="market-hero-side">
          <Card className="market-filter-card" variant="borderless">
            <Space direction="vertical" size={12} style={{ width: '100%' }}>
              <div>
                <Text className="market-side-label">场景模式</Text>
                <Select
                  style={{ width: '100%' }}
                  value={studentId}
                  onChange={setStudentId}
                  options={[
                    { label: '市场模式（不绑定学生）', value: '' },
                    ...students.map((s, index) => ({ label: presentStudentOption(s, index), value: s.student_id }))
                  ]}
                  showSearch
                  filterOption={false}
                  onSearch={(value) => { void searchStudents(String(value || '').trim()) }}
                />
              </div>
              <div>
                <Text className="market-side-label">方向分群</Text>
                <Select style={{ width: '100%' }} options={familyOptions} value={jobFamily} onChange={setJobFamily} />
              </div>
              <div>
                <Text className="market-side-label">排序策略</Text>
                <Select style={{ width: '100%' }} options={strategyOptions} value={strategy} onChange={setStrategy} disabled={!canWrite} />
              </div>
              <div>
                <Text className="market-side-label">关键词筛选</Text>
                <Input.Search prefix={<SearchOutlined />} placeholder="例如：前端 / 测试 / 运维 / 数据" value={keyword} onChange={e => setKeyword(e.target.value)} onSearch={() => void load()} />
              </div>
              <Button type="primary" block onClick={() => void load()} loading={loading}>刷新岗位驾驶舱</Button>
              <Text type="secondary">{studentId && canWrite ? '当前为个性化模式：会叠加匹配分、偏好策略与行为信号。' : '当前为市场模式：侧重岗位结构与角色样本。'}</Text>
            </Space>
          </Card>
        </div>
      </div>

      <div className="market-main-grid">
        <Card title="市场结构概览" extra={<Tag color="cyan">{topCities.length} 个重点城市</Tag>}>
          <Row gutter={[16, 16]}>
            <Col span={12}>
              <div className="market-panel-block">
                <Text className="market-panel-title">薪资带分布</Text>
                <div className="market-band-list">
                  {salaryBands.length ? salaryBands.map((item: any) => (
                    <div key={item.name} className="market-band-item">
                      <div className="market-band-head">
                        <span>{item.name}</span>
                        <b>{item.count}</b>
                      </div>
                      <Progress percent={percentOf(totalJobs, Number(item.count || 0))} showInfo={false} strokeColor="#4da3ff" />
                    </div>
                  )) : <Empty description="暂无薪资结构" image={Empty.PRESENTED_IMAGE_SIMPLE} />}
                </div>
              </div>
            </Col>
            <Col span={12}>
              <div className="market-panel-block">
                <Text className="market-panel-title">城市与行业热区</Text>
                <div className="market-chip-group">
                  {topCities.slice(0, 10).map((item: any) => <Tag key={item.name}>{item.name} {item.count}</Tag>)}
                </div>
                <div className="market-chip-group market-chip-group-tight">
                  {topIndustries.slice(0, 10).map((item: any) => <Tag color="geekblue" key={item.name}>{item.name} {item.count}</Tag>)}
                </div>
              </div>
            </Col>
            <Col span={12}>
              <div className="market-panel-block">
                <Text className="market-panel-title">企业性质</Text>
                <div className="market-chip-group">
                  {topCompanyTypes.slice(0, 8).map((item: any) => <Tag color="purple" key={item.name}>{item.name} {item.count}</Tag>)}
                  {!topCompanyTypes.length ? <Text type="secondary">暂无企业性质分布数据</Text> : null}
                </div>
              </div>
            </Col>
            <Col span={12}>
              <div className="market-panel-block">
                <Text className="market-panel-title">企业规模</Text>
                <div className="market-chip-group">
                  {topCompanySizes.slice(0, 8).map((item: any) => <Tag color="gold" key={item.name}>{item.name} {item.count}</Tag>)}
                  {!topCompanySizes.length ? <Text type="secondary">暂无企业规模分布数据</Text> : null}
                </div>
              </div>
            </Col>
          </Row>
        </Card>

        <Card title="热门方向分群" extra={<Tag color="green">{familyCards.length} 类</Tag>}>
          <div className="market-family-grid">
            {familyCards.length ? familyCards.map((item: any) => (
              <div key={item.name} className={`market-family-card ${jobFamily === item.name ? 'active' : ''}`} onClick={() => setJobFamily(item.name)}>
                <div className="market-family-title">{item.label || item.name}</div>
                <div className="market-family-count">{item.count} 个角色</div>
                <Progress percent={percentOf(Number(overview?.counts?.roles || 0), Number(item.count || 0))} showInfo={false} strokeColor="#2fd6a7" />
              </div>
            )) : <Empty description="暂无方向分群" image={Empty.PRESENTED_IMAGE_SIMPLE} />}
          </div>
        </Card>
      </div>

      <div className="market-main-grid">
        <Card title="能力需求热区（TOP20）" extra={<Tag color="blue">{topHardSkills.length} 项</Tag>}>
          <Space direction="vertical" size={14} style={{ width: '100%' }}>
            <div className="market-panel-block">
              <Text className="market-panel-title">高频硬技能</Text>
              <div className="market-chip-group">
                {topHardSkills.slice(0, 20).map((item: any, idx: number) => (
                  <Tag color={idx < 6 ? 'geekblue' : 'default'} key={`${item?.name || 'skill'}-${idx}`}>
                    {item?.name || '未命名技能'} {item?.count ? `(${item.count})` : ''}
                  </Tag>
                ))}
              </div>
            </div>
            <Row gutter={[14, 14]}>
              <Col span={8}>
                <div className="market-panel-block">
                  <Text className="market-panel-title">当前方向数</Text>
                  <div className="market-pulse-value">{marketPulse.roleCount}</div>
                </div>
              </Col>
              <Col span={8}>
                <div className="market-panel-block">
                  <Text className="market-panel-title">平均样本规模</Text>
                  <div className="market-pulse-value">{marketPulse.avgMembers}</div>
                </div>
              </Col>
              <Col span={8}>
                <div className="market-panel-block">
                  <Text className="market-panel-title">高转岗弹性方向</Text>
                  <div className="market-pulse-value">{marketPulse.strongSwitch}</div>
                </div>
              </Col>
            </Row>
          </Space>
        </Card>
      </div>

      <Card
        title="推荐依据与知识库命中"
        extra={<Tag color="purple">{kbRefs.length} 条证据</Tag>}
      >
        <Space direction="vertical" size={12} style={{ width: '100%' }}>
          <div className="market-evidence-head">
            <Tag color={studentId && canWrite ? 'green' : 'default'}>
              {studentId && canWrite ? '个性化推荐模式' : '市场模式'}
            </Tag>
            <Tag color="blue">行为信号 {behaviorEventsUsed}</Tag>
          </div>
          {!studentId || !canWrite ? (
            <Alert
              type="info"
              showIcon
              message="当前为市场模式，不展示个性化知识库证据。"
              description="选择学生并使用推荐模式后，将显示岗位推荐时命中的知识库条目与查询关键词。"
            />
          ) : null}
          {studentId && canWrite && !kbRefs.length ? (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无知识库命中，可尝试输入更具体关键词（如岗位名/技能名）" />
          ) : null}
          {studentId && canWrite && kbRefs.length ? (
            <div className="market-evidence-list">
              {kbRefs.slice(0, 8).map((ref: any, idx: number) => (
                <div key={`${ref?.doc_id || ref?.path || idx}`} className="market-evidence-item">
                  <div className="market-evidence-title">{ref?.title || `知识条目 ${idx + 1}`}</div>
                  <div className="market-evidence-meta">
                    <Tag>score {Number(ref?.score || 0).toFixed(3)}</Tag>
                    {(ref?.matched_queries || []).slice(0, 4).map((q: string) => <Tag color="blue" key={q}>{q}</Tag>)}
                  </div>
                  {ref?.snippet ? <Paragraph className="market-evidence-snippet">{String(ref.snippet)}</Paragraph> : null}
                  {ref?.path ? <Text type="secondary">来源：{String(ref.path)}</Text> : null}
                </div>
              ))}
            </div>
          ) : null}
        </Space>
      </Card>

      <div className="market-main-grid" style={{ gridTemplateColumns: '1fr' }}>
        <Card title="高频能力需求热区" extra={<Tag color="blue">{topHardSkills.length} 项</Tag>}>
          <div className="market-skill-cloud">
            {topHardSkills.length ? topHardSkills.map((item: any) => (
              <div key={item.name} className="market-skill-pill">
                <span>{item.name}</span>
                <b>{item.count}</b>
              </div>
            )) : <Empty description="暂无能力需求热区" image={Empty.PRESENTED_IMAGE_SIMPLE} />}
          </div>
        </Card>
      </div>

      <Card title="代表角色工作台" extra={<Tag color="cyan">{items.length} 个方向</Tag>}>
        <div className="market-table-hint">
          <Text type="secondary">点击角色名称可查看该方向的画像、垂直晋升链路、转岗路径解释与样本岗位明细。</Text>
        </div>
        <Table rowKey="role_id" loading={loading} columns={columns as any} dataSource={items} pagination={{ pageSize: 10 }} />
      </Card>

      <Drawer
        open={!!detail}
        width={980}
        title={detail?.role ? presentRoleName(detail.role) : activeRole ? presentRoleName(activeRole) : '角色详情'}
        onClose={() => {
          setDetail(null)
          if (jobDetailFromRole) {
            closeJobDetail()
          }
        }}
      >
        {detail ? (
          <Space direction="vertical" size={20} style={{ width: '100%' }}>
            <Card size="small" title="角色画像概览">
              <Row gutter={[16, 16]}>
                <Col span={12}><Text strong>岗位族：</Text> <Tag>{detail.role?.job_family_label || familyLabel(detail.role?.job_family)}</Tag></Col>
                <Col span={12}><Text strong>层级：</Text> <Tag>{detail.role?.level_label_zh || levelLabel(detail.role?.level_label)}</Tag></Col>
                <Col span={12}><Text strong>样本规模：</Text> <Tag color="green">{detail.member_count || 0} 条</Tag></Col>
                <Col span={12}><Text strong>转岗路径：</Text> <Tag color="purple">{(detail.switch_paths || []).length} 条</Tag></Col>
                <Col span={24}><Text strong>硬技能：</Text><div style={{ marginTop: 8 }}><SkillTags items={detail?.profile?.profile?.top_hard_skills || []} /></div></Col>
                <Col span={24}><Text strong>软技能：</Text><div style={{ marginTop: 8 }}><SkillTags items={detail?.profile?.profile?.top_soft_skills || []} /></div></Col>
                <Col span={24}><Text strong>建议证书：</Text><div style={{ marginTop: 8 }}><SkillTags items={detail?.profile?.profile?.top_certificates || []} /></div></Col>
              </Row>
            </Card>

            <Row gutter={[16, 16]}>
              <Col span={12}>
                <Card size="small" title="垂直晋升路径">
                  <div className="market-drawer-paths">
                    <PathFlow
                      nodes={detail.vertical_path || []}
                      nodeLabel={presentRoleName}
                      emptyText="暂无垂直路径"
                    />
                  </div>
                </Card>
              </Col>
              <Col span={12}>
                <Card size="small" title="转岗路径解释">
                  <Space direction="vertical" size={12} style={{ width: '100%' }}>
                    {(detail.switch_paths || []).map((path: any, idx: number) => (
                      <div key={idx} className="market-switch-card">
                        <div className="market-switch-title">
                          <PathFlow
                            nodes={path.nodes || []}
                            nodeLabel={presentRoleName}
                            compact
                          />
                        </div>
                        {(path.edges || []).map((edge: any, edgeIdx: number) => (
                          <div key={edgeIdx} className="market-switch-edge">
                            <div><Text strong>共享技能：</Text> {(edge.shared_skills || []).map((s: string) => <Tag key={s}>{s}</Tag>)}</div>
                            <div><Text strong>补课点：</Text> {(edge.gap_skills || []).map((s: string) => <Tag color="orange" key={s}>{s}</Tag>)}</div>
                          </div>
                        ))}
                      </div>
                    ))}
                    {!(detail.switch_paths || []).length ? <Empty description="暂无转岗路径" image={Empty.PRESENTED_IMAGE_SIMPLE} /> : null}
                  </Space>
                </Card>
              </Col>
            </Row>

            <Card size="small" title="代表岗位样本">
              <Table
                rowKey="job_id"
                size="small"
                pagination={false}
                dataSource={detail.member_jobs || []}
                columns={[
                  { title: '岗位名', dataIndex: 'title' },
                  { title: '公司', dataIndex: 'company_name' },
                  { title: '地点', dataIndex: 'location' },
                  { title: '薪资', render: (_: any, row: any) => `${formatCurrency(row.salary_min)} - ${formatCurrency(row.salary_max)}` },
                  {
                    title: '岗位画像',
                    render: (_: any, row: any) => (
                      <Button size="small" onClick={() => void openJobProfile(row.job_id, true)}>
                        查看画像
                      </Button>
                    )
                  }
                ]}
              />
            </Card>

            <Drawer
              open={!!jobDetail && !!detail && jobDetailFromRole}
              width={620}
              title={jobDetail?.job?.title || jobDetail?.job?.job_id || '岗位画像详情'}
              onClose={closeJobDetail}
              getContainer={false}
              mask={false}
              zIndex={1200}
            >
              {renderJobDetailContent()}
            </Drawer>
          </Space>
        ) : null}
      </Drawer>

      <Drawer
        open={!!jobDetail && (!detail || !jobDetailFromRole)}
        width={760}
        title={jobDetail?.job?.title || jobDetail?.job?.job_id || '岗位画像详情'}
        onClose={closeJobDetail}
        zIndex={1200}
      >
        {renderJobDetailContent()}
      </Drawer>
    </Space>
  )
}
