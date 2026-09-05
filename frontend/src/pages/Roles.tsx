import React, { useEffect, useMemo, useState } from 'react'
import { Alert, Button, Card, Empty, Input, Row, Col, Space, Tag, Typography } from 'antd'
import { ReloadOutlined, SearchOutlined } from '@ant-design/icons'
import { api } from '../api/client'
import { CareerRoadmapGraph } from '../components/CareerRoadmapGraph'
import { familyChoiceOptions, familyLabel, levelLabel } from '../constants/labels'
import { presentRoleName } from '../utils/present'

const { Text, Title } = Typography
const LEVEL_ORDER = ['junior', 'mid', 'senior', 'lead', 'director']

function normalizeSkillName(item: any) {
  return String(item?.name || item?.mention || item?.skill_id || '').trim()
}

function normalizePathBlock(path: any): { nodes: any[]; edges: any[] } {
  if (Array.isArray(path?.nodes)) return { nodes: path.nodes || [], edges: path.edges || [] }
  if (Array.isArray(path)) return { nodes: path, edges: [] }
  return { nodes: [], edges: [] }
}

export default function Roles() {
  const [loading, setLoading] = useState(false)
  const [loadError, setLoadError] = useState('')
  const [overview, setOverview] = useState<any>(null)
  const [readiness, setReadiness] = useState<any>(null)
  const [roleList, setRoleList] = useState<any[]>([])
  const [featuredRoles, setFeaturedRoles] = useState<any[]>([])
  const [activeId, setActiveId] = useState('')
  const [active, setActive] = useState<any>(null)
  const [family, setFamily] = useState('')
  const [keyword, setKeyword] = useState('')

  const openRole = async (roleId: string) => {
    if (!roleId) return
    setActiveId(roleId)
    const res = await api.get(`/insights/role/${roleId}`, { params: { switch_top_k: 6 } })
    setActive(res.data || null)
  }

  const load = async () => {
    setLoading(true)
    setLoadError('')
    try {
      const [overviewRes, readinessRes, rolesRes, featuredRes] = await Promise.all([
        api.get('/insights/overview', { params: { top_n: 12 } }),
        api.get('/insights/competition/readiness'),
        api.get('/roles', { params: { limit: 5000, offset: 0, job_family: family || undefined } }),
        api.get('/insights/role_samples', { params: { top_k: 50, job_family: family || undefined } })
      ])

      const roles = Array.isArray(rolesRes.data?.items) ? rolesRes.data.items : []
      const featured = Array.isArray(featuredRes.data?.items) ? featuredRes.data.items : []
      setOverview(overviewRes.data || null)
      setReadiness(readinessRes.data || null)
      setRoleList(roles)
      setFeaturedRoles(featured)

      const targetRoleId = activeId && roles.some((item: any) => item.role_id === activeId)
        ? activeId
        : String((featured[0] || roles[0] || {}).role_id || '')
      if (targetRoleId) await openRole(targetRoleId)
      else setActive(null)
    } catch (e: any) {
      setLoadError(String(e?.response?.data?.detail || e?.message || '加载角色数据失败'))
      setRoleList([])
      setFeaturedRoles([])
      setActive(null)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load()
  }, [family])

  const filteredRoles = useMemo(() => {
    const source = featuredRoles.length ? featuredRoles : roleList
    const kw = keyword.trim().toLowerCase()
    if (!kw) return source
    return source.filter((item: any) => {
      const haystack = [
        presentRoleName(item),
        item?.job_family_label || familyLabel(item?.job_family),
        item?.base_role || ''
      ].join(' ').toLowerCase()
      return haystack.includes(kw)
    })
  }, [featuredRoles, roleList, keyword])

  const metrics = useMemo(() => {
    const roleCount = Number(overview?.counts?.roles || roleList.length || 0)
    const familyCount = new Set(roleList.map((item: any) => String(item?.job_family || 'general'))).size
    const verticalReady = Number(readiness?.metrics?.roles_with_vertical_paths || 0)
    const switchReady = Number(readiness?.metrics?.roles_with_switch_paths || 0)
    return [
      { label: '角色', value: roleCount },
      { label: '方向', value: familyCount },
      { label: '晋升链', value: verticalReady },
      { label: '转岗链', value: switchReady }
    ]
  }, [overview, readiness, roleList])

  const activeRole = active?.role || null
  const activeProfile = active?.profile?.profile || {}
  const activeVertical = Array.isArray(active?.vertical_path) ? active.vertical_path : []
  const activeSwitches = Array.isArray(active?.switch_paths) ? active.switch_paths : []
  const samplePaths = Array.isArray(readiness?.sample_switch_roles) ? readiness.sample_switch_roles : []
  const routeBlueprint = useMemo(() => {
    const grouped: Record<string, any[]> = {}
    for (const role of roleList) {
      const key = String(role?.job_family || 'general')
      grouped[key] = grouped[key] || []
      grouped[key].push(role)
    }
    const out = Object.entries(grouped).map(([jobFamily, roles]) => {
      const sorted = [...roles].sort((a: any, b: any) => LEVEL_ORDER.indexOf(String(a?.level_label || 'mid')) - LEVEL_ORDER.indexOf(String(b?.level_label || 'mid')))
      return {
        jobFamily,
        label: familyLabel(jobFamily),
        levels: sorted
      }
    })
    out.sort((a, b) => b.levels.length - a.levels.length)
    return out.slice(0, 8)
  }, [roleList])

  return (
    <Space direction="vertical" size={20} style={{ width: '100%' }}>
      {loadError ? <Alert type="warning" showIcon message="角色页数据加载异常" description={loadError} /> : null}

      <div className="atlas-hero">
        <div className="atlas-hero-main">
          <Text className="atlas-kicker">路径</Text>
          <Title level={2} className="atlas-title">职业路径</Title>
          <div className="atlas-metric-grid">
            {metrics.map((item) => (
              <div key={item.label} className="atlas-metric-card">
                <div>
                  <div className="atlas-metric-label">{item.label}</div>
                  <div className="atlas-metric-value">{item.value}</div>
                </div>
              </div>
            ))}
          </div>
        </div>
        <div className="atlas-hero-side">
          <Card className="atlas-side-card" variant="borderless">
            <Space direction="vertical" size={14} style={{ width: '100%' }}>
              <Input
                prefix={<SearchOutlined />}
                value={keyword}
                onChange={(e) => setKeyword(e.target.value)}
                placeholder="搜索方向"
              />
              <div className="atlas-chip-row">
                <Tag className={!family ? 'atlas-chip-active' : ''} onClick={() => setFamily('')}>全部</Tag>
                {familyChoiceOptions.map((item) => (
                  <Tag key={item.value} className={family === item.value ? 'atlas-chip-active' : ''} onClick={() => setFamily(item.value)}>
                    {item.label}
                  </Tag>
                ))}
              </div>
              <Button icon={<ReloadOutlined />} onClick={() => void load()} loading={loading}>刷新</Button>
            </Space>
          </Card>
        </div>
      </div>

      <Card title="IT 多方向成长路线图（图谱）">
        <CareerRoadmapGraph
          onPickKeyword={(value: string) => setKeyword(value)}
          activeKeyword={keyword}
        />
      </Card>

      <Card title="岗位族成长路线图（树状）">
        <div className="atlas-blueprint-grid">
          {routeBlueprint.length ? routeBlueprint.map((track) => (
            <div key={track.jobFamily} className="atlas-blueprint-card">
              <div className="atlas-blueprint-head">
                <Tag color="blue">{track.label}</Tag>
              </div>
              <div className="atlas-blueprint-levels">
                {(track.levels || []).map((node: any, index: number) => (
                  <React.Fragment key={node.role_id || `${track.jobFamily}-${index}`}>
                    <div
                      className={`atlas-blueprint-node ${activeId === node?.role_id ? 'active' : ''}`}
                      role="button"
                      tabIndex={0}
                      onClick={() => node?.role_id ? void openRole(node.role_id) : undefined}
                      onKeyDown={(e) => {
                        if ((e.key === 'Enter' || e.key === ' ') && node?.role_id) {
                          e.preventDefault()
                          void openRole(node.role_id)
                        }
                      }}
                    >
                      <div className="atlas-blueprint-node-level">{levelLabel(node?.level_label)}</div>
                      <div className="atlas-blueprint-node-title">{presentRoleName(node)}</div>
                    </div>
                    {index < track.levels.length - 1 ? <span className="atlas-blueprint-arrow">→</span> : null}
                  </React.Fragment>
                ))}
              </div>
            </div>
          )) : (
            <Empty description="暂无路线图数据，可先在管理台执行角色重建/图谱重建" />
          )}
        </div>
      </Card>

      <div className="atlas-grid">
        <div className="atlas-left-column">
          <Card title="角色列表" extra={<Tag color="blue">{filteredRoles.length}</Tag>}>
            <div className="atlas-role-list">
              {!loading && !filteredRoles.length ? <Empty description="暂无角色" /> : null}
              {filteredRoles.map((item: any) => (
                <div
                  key={item.role_id}
                  className={`atlas-role-item ${activeId === item.role_id ? 'active' : ''}`}
                  onClick={() => void openRole(item.role_id)}
                >
                  <div>
                    <div className="atlas-role-item-title">{presentRoleName(item)}</div>
                    <div className="atlas-role-item-meta">{item?.job_family_label || familyLabel(item?.job_family)} · {item?.level_label_zh || levelLabel(item?.level_label)}</div>
                  </div>
                  <Tag color="green">{item?.member_count || 0}</Tag>
                </div>
              ))}
            </div>
          </Card>
        </div>

        <div className="atlas-center-column">
          <Card title={activeRole ? presentRoleName(activeRole) : '角色详情'}>
            {!activeRole ? <Empty description="请选择角色" /> : (
              <Space direction="vertical" size={18} style={{ width: '100%' }}>
                <Row gutter={[12, 12]}>
                  <Col span={12}><Tag color="blue">{familyLabel(activeRole?.job_family)}</Tag></Col>
                  <Col span={12}><Tag>{levelLabel(activeRole?.level_label)}</Tag></Col>
                  <Col span={12}><Tag color="green">样本 {active?.member_count || 0}</Tag></Col>
                  <Col span={12}><Tag color="purple">转岗 {activeSwitches.length || 0}</Tag></Col>
                </Row>

                <div>
                  <Text className="panel-subtitle">技能</Text>
                  <div className="atlas-skill-cloud atlas-skill-cloud-strong">
                    {(activeProfile?.top_hard_skills || []).slice(0, 16).map((item: any) => {
                      const name = normalizeSkillName(item)
                      return name ? <Tag key={name}>{name}</Tag> : null
                    })}
                  </div>
                </div>

                <div>
                  <Text className="panel-subtitle">晋升路径</Text>
                  <div className="atlas-vertical-track">
                    {activeVertical.length ? activeVertical.map((node: any, idx: number) => (
                      <React.Fragment key={node.role_id || idx}>
                        <div className={`atlas-vertical-node ${idx === 0 ? 'origin' : idx === activeVertical.length - 1 ? 'target' : ''}`}>
                          <div className="atlas-vertical-level">{levelLabel(node?.level_label)}</div>
                          <div className="atlas-vertical-title">{presentRoleName(node)}</div>
                          <div className="atlas-vertical-meta">{familyLabel(node?.job_family)}</div>
                        </div>
                        {idx < activeVertical.length - 1 ? <div className="atlas-vertical-link" /> : null}
                      </React.Fragment>
                    )) : <Empty description="暂无路径" />}
                  </div>
                </div>
              </Space>
            )}
          </Card>

          <Card title="转岗路径" extra={<Tag color="cyan">{activeSwitches.length}</Tag>}>
            {!activeRole ? <Empty description="请选择角色" /> : (
              <div className="atlas-switch-stack">
                {activeSwitches.length ? activeSwitches.slice(0, 6).map((path: any, idx: number) => {
                  const block = normalizePathBlock(path)
                  return (
                    <div key={idx} className="atlas-switch-card">
                      <div className="atlas-switch-route">
                        {block.nodes.map((node: any, nodeIdx: number) => (
                          <React.Fragment key={`${idx}-${nodeIdx}`}>
                            <div className={`atlas-switch-node ${nodeIdx === 0 ? 'source' : nodeIdx === block.nodes.length - 1 ? 'target' : ''}`}>
                              <div className="atlas-switch-title">{presentRoleName(node)}</div>
                              <div className="atlas-switch-meta">{familyLabel(node?.job_family)} · {levelLabel(node?.level_label)}</div>
                            </div>
                            {nodeIdx < block.nodes.length - 1 ? <div className="atlas-switch-arrow">→</div> : null}
                          </React.Fragment>
                        ))}
                      </div>
                      <div className="atlas-switch-edge-list">
                        {block.edges.map((edge: any, edgeIdx: number) => (
                          <div key={edgeIdx} className="atlas-switch-edge">
                            <div>
                              <Text strong>共享技能</Text>
                              <div className="atlas-skill-cloud">
                                {(edge?.shared_skills || []).length
                                  ? (edge?.shared_skills || []).map((skill: string) => <Tag key={skill}>{skill}</Tag>)
                                  : <Text type="secondary">暂无共享技能证据，建议先补齐角色画像中的技能标注。</Text>}
                              </div>
                            </div>
                            <div>
                              <Text strong>待补技能</Text>
                              <div className="atlas-skill-cloud">
                                {(edge?.gap_skills || []).length
                                  ? (edge?.gap_skills || []).map((skill: string) => <Tag color="orange" key={skill}>{skill}</Tag>)
                                  : <Text type="secondary">暂无明确待补技能，建议结合目标岗位JD再做补课拆解。</Text>}
                              </div>
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )
                }) : <Empty description="暂无转岗路径" />}
              </div>
            )}
          </Card>
        </div>

        <div className="atlas-right-column">
          <Card title="样例路径" extra={<Tag color="purple">{samplePaths.length}</Tag>}>
            <div className="atlas-sample-stack">
              {samplePaths.length ? samplePaths.map((item: any) => (
                <div key={item?.role_id} className="atlas-sample-card" onClick={() => item?.role_id ? void openRole(item.role_id) : undefined}>
                  <div className="atlas-sample-title">{presentRoleName(item)}</div>
                  {(item?.paths || []).slice(0, 2).map((path: any[], idx: number) => (
                    <div key={idx} className="atlas-sample-route">
                      {(path || []).map((node: any, nodeIdx: number) => (
                        <React.Fragment key={`${idx}-${nodeIdx}`}>
                          <Tag>{presentRoleName(node)}</Tag>
                          {nodeIdx < path.length - 1 ? <span className="path-arrow">→</span> : null}
                        </React.Fragment>
                      ))}
                    </div>
                  ))}
                </div>
              )) : <Empty description="暂无样例" />}
            </div>
          </Card>
        </div>
      </div>
    </Space>
  )
}
