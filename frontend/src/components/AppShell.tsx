import React, { useEffect, useMemo, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import {
  ApartmentOutlined,
  CustomerServiceOutlined,
  DashboardOutlined,
  DotChartOutlined,
  IdcardOutlined,
  FileSearchOutlined,
  FileTextOutlined,
  FullscreenExitOutlined,
  FullscreenOutlined,
  FormOutlined,
  LogoutOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
  RadarChartOutlined,
  SettingOutlined,
  UserOutlined
} from '@ant-design/icons'
import { Button, Dropdown, Layout, Menu, Space, Tag, Tour, Typography } from 'antd'
import type { MenuProps } from 'antd'
import { UserRole, useAuth } from '../auth/AuthContext'
import { presentUserName } from '../utils/present'

const { Sider, Header, Content } = Layout
const { Title, Text } = Typography

type NavItem = {
  key: string
  label: string
  icon: React.ReactNode
  roles?: UserRole[]
  children?: NavItem[]
}

type FlatRoute = {
  key: string
  label: string
  parentKeys: string[]
}

const navItems: NavItem[] = [
  { key: '/', label: 'Dashboard', icon: <DashboardOutlined /> },
  {
    key: 'job-center',
    label: '岗位与路径',
    icon: <RadarChartOutlined />,
    children: [
      { key: '/jobs', label: '岗位洞察', icon: <RadarChartOutlined /> },
      { key: '/match', label: '匹配诊断', icon: <FileSearchOutlined /> },
      { key: '/roles', label: '职业路径', icon: <ApartmentOutlined /> }
    ]
  },
  {
    key: 'student-center',
    label: '学生与报告',
    icon: <UserOutlined />,
    children: [
      { key: '/student', label: '学生画像', icon: <UserOutlined /> },
      { key: '/resume', label: 'AI简历', icon: <FormOutlined /> },
      { key: '/interview', label: '模拟面试', icon: <CustomerServiceOutlined /> },
      { key: '/interview/coding', label: '笔试探察', icon: <FileSearchOutlined /> },
      { key: '/interview/face', label: '人脸认证', icon: <IdcardOutlined /> },
      { key: '/report', label: '规划报告', icon: <FileTextOutlined /> }
    ]
  },
  { key: '/assistant', label: '生涯顾问', icon: <DotChartOutlined /> },
  {
    key: 'system-center',
    label: '系统管理',
    icon: <SettingOutlined />,
    roles: ['admin'],
    children: [
      { key: '/operations', label: '运营配置', icon: <SettingOutlined />, roles: ['admin'] },
      { key: '/accuracy-lab', label: '准确率验真', icon: <FileSearchOutlined />, roles: ['admin'] }
    ]
  }
]

const pageDescriptions: Record<string, string> = {
  '/': '核心数据总览',
  '/jobs': '岗位供需、热度与招聘环境分析',
  '/student': '学生档案、能力画像与标签补全',
  '/match': '岗位匹配评分与差距诊断',
  '/resume': 'AI简历模板编辑、生成与优化',
  '/interview': '岗位模拟面试、语音问答与复盘素材',
  '/interview/coding': '两轮 Java 笔试、代码点评与岗位技能验证',
  '/interview/face': '拍照注册、身份认证与面试状态校验',
  '/roles': '晋升与转岗路径可视化',
  '/report': '职业规划报告生成与排版',
  '/assistant': '对话式顾问与路线咨询',
  '/operations': '系统参数、模型链路与任务管理',
  '/accuracy-lab': '人岗匹配与画像准确率验真'
}

const roleLabels: Record<UserRole, string> = {
  admin: '管理员',
  operator: '老师',
  viewer: '只读',
  student: '个人用户'
}

const roleCapabilityTexts: Record<UserRole, string[]> = {
  admin: ['查看', '编辑', '系统配置'],
  operator: ['查看', '编辑', '生成报告'],
  viewer: ['仅查看'],
  student: ['我的画像', '职业匹配', '个人报告']
}

const GUIDE_SEEN_KEY = 'career_os_onboarding_v1_seen'

const GUIDE_ROUTE_BY_STEP: Record<number, string> = {
  0: '/',
  1: '/',
  2: '/jobs',
  3: '/student',
  4: '/match',
  5: '/roles',
  6: '/interview',
  7: '/report',
  8: '/assistant'
}

function allowRole(item: NavItem, role: UserRole) {
  if (!item.roles || !item.roles.length) return true
  return item.roles.includes(role)
}

function selectedKeyFromPath(pathname: string, items: FlatRoute[]) {
  const exact = items.find(item => item.key === pathname)
  if (exact) return exact.key
  const matched = items.find(item => item.key !== '/' && pathname.startsWith(item.key))
  return matched?.key || '/'
}

function buildMenu(items: NavItem[], role: UserRole, parentKeys: string[] = []): {
  menuItems: NonNullable<MenuProps['items']>
  flatRoutes: FlatRoute[]
} {
  const menuItems: NonNullable<MenuProps['items']> = []
  const flatRoutes: FlatRoute[] = []

  for (const item of items) {
    if (!allowRole(item, role)) continue

    const nextParentKeys = item.children && item.children.length ? [...parentKeys, item.key] : parentKeys

    if (item.children && item.children.length) {
      const childResult = buildMenu(item.children, role, nextParentKeys)
      if (childResult.menuItems.length) {
        menuItems.push({
          key: item.key,
          label: item.label,
          icon: item.icon,
          children: childResult.menuItems
        })
      }
      flatRoutes.push(...childResult.flatRoutes)
      continue
    }

    menuItems.push({
      key: item.key,
      label: item.label,
      icon: item.icon
    })
    flatRoutes.push({
      key: item.key,
      label: item.label,
      parentKeys
    })
  }

  return { menuItems, flatRoutes }
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const location = useLocation()
  const navigate = useNavigate()
  const { user, logout } = useAuth()
  const role = user?.role || 'viewer'
  const [collapsed, setCollapsed] = useState(false)
  const [openKeys, setOpenKeys] = useState<string[]>([])
  const [isFullscreen, setIsFullscreen] = useState(false)
  const [guideOpen, setGuideOpen] = useState(false)
  const [guideStep, setGuideStep] = useState(0)
  const guideInitedRef = useRef(false)
  const menuRef = useRef<HTMLDivElement | null>(null)
  const pageHeroRef = useRef<HTMLDivElement | null>(null)
  const capabilityRef = useRef<HTMLDivElement | null>(null)

  const { menuItems, flatRoutes } = useMemo(() => buildMenu(navItems, role), [role])
  const selectedKey = selectedKeyFromPath(location.pathname, flatRoutes)
  const selected = flatRoutes.find(item => item.key === selectedKey)
  const selectedParentKeys = selected?.parentKeys || []

  useEffect(() => {
    if (!collapsed) {
      setOpenKeys(selectedParentKeys)
    }
  }, [collapsed, selectedKey])

  useEffect(() => {
    const syncFullscreen = () => {
      setIsFullscreen(Boolean(document.fullscreenElement))
    }

    syncFullscreen()
    document.addEventListener('fullscreenchange', syncFullscreen)
    return () => document.removeEventListener('fullscreenchange', syncFullscreen)
  }, [])

  useEffect(() => {
    if (guideInitedRef.current) return
    guideInitedRef.current = true
    const seen = localStorage.getItem(GUIDE_SEEN_KEY)
    if (!seen) {
      setGuideStep(0)
      setGuideOpen(true)
    }
  }, [])

  useEffect(() => {
    if (!guideOpen) return
    const route = GUIDE_ROUTE_BY_STEP[guideStep]
    if (route && location.pathname !== route) {
      navigate(route)
    }
  }, [guideOpen, guideStep, location.pathname, navigate])

  const doLogout = async () => {
    await logout()
    navigate('/login', { replace: true })
  }

  const toggleFullscreen = async () => {
    try {
      if (!document.fullscreenElement && document.documentElement.requestFullscreen) {
        await document.documentElement.requestFullscreen()
      } else if (document.exitFullscreen) {
        await document.exitFullscreen()
      }
    } catch (error) {
      console.error('[AppShell] fullscreen toggle failed:', error)
    }
  }

  const accountMenuItems: MenuProps['items'] = [
    { key: 'role', label: `角色：${roleLabels[role]}`, disabled: true },
    { key: 'name', label: `账号：${presentUserName(user)}`, disabled: true },
    { type: 'divider' },
    { key: 'logout', icon: <LogoutOutlined />, label: '退出登录' }
  ]

  const tourSteps = useMemo(() => {
    const rawSteps = [
    {
      title: '步骤 1/9 · 快速总览',
      description: '先看首页关键状态：岗位/角色/学生画像/报告数量，先判断当前是“数据不足”还是“匹配不足”。',
      target: () => pageHeroRef.current
    },
    {
      title: '步骤 2/9 · 智能仪表盘先看总览',
      description: '主页只保留关键状态：画像进度、岗位推荐、匹配度、待办任务和行业快报。先从这里判断下一步最该补什么。',
      target: () => capabilityRef.current
    },
    {
      title: '步骤 3/9 · 岗位洞察',
      description: '进入岗位洞察，先看方向分群、城市/行业和能力热区，确认样本是否覆盖你的目标方向。',
      target: () => menuRef.current
    },
    {
      title: '步骤 4/9 · 学生画像',
      description: '在学生页先补齐简历与关键字段（技能、经历、MBTI、期望），再进入匹配诊断。',
      target: () => menuRef.current
    },
    {
      title: '步骤 5/9 · 匹配诊断',
      description: '匹配页先看 Top 结果与诊断，再点开单条查看“优势/短板/候选技能/语义复核”。',
      target: () => menuRef.current
    },
    {
      title: '步骤 6/9 · 职业路径',
      description: '路径页重点看垂直晋升与转岗链路，结合共享技能与待补技能确定学习路线。',
      target: () => menuRef.current
    },
    {
      title: '步骤 7/9 · 模拟面试',
      description: '模拟面试页把岗位问题、语音回答和复盘建议串起来。',
      target: () => menuRef.current
    },
    {
      title: '步骤 8/9 · 规划报告',
      description: '报告页用于输出评审材料：一键生成后可检查、润色、导出 PDF/DOCX。',
      target: () => menuRef.current
    },
    {
      title: '步骤 9/9 · 对话顾问',
      description: '最后用顾问页做问答式复盘，快速解释“为什么推荐、如何补齐、下一步做什么”。',
      target: () => menuRef.current
    }
  ]
    return rawSteps.map((step, index) => ({
      ...step,
      prevButtonProps: { children: '< 上一步' },
      nextButtonProps: { children: index >= rawSteps.length - 1 ? '完成' : '下一步 >' }
    }))
  }, [])

  return (
    <Layout className="career-shell admin-shell">
      <Sider
        className="admin-shell-sider"
        width={252}
        collapsedWidth={76}
        collapsed={collapsed}
        breakpoint="lg"
        onBreakpoint={broken => setCollapsed(broken)}
        trigger={null}
        theme="dark"
      >
        <div className="admin-shell-brand" onClick={() => navigate('/')}>
          <div className="admin-shell-brand-mark">例</div>
          {!collapsed ? (
            <div>
              <Title level={5} className="admin-shell-brand-title">智能就业平台</Title>
              <Text className="admin-shell-brand-subtitle">Career Command Center</Text>
            </div>
          ) : null}
        </div>
        <div ref={menuRef}>
          <Menu
            mode="inline"
            theme="dark"
            className="admin-shell-menu"
            selectedKeys={[selectedKey]}
            openKeys={collapsed ? [] : openKeys}
            items={menuItems}
            onOpenChange={keys => setOpenKeys(keys as string[])}
            onClick={({ key }) => navigate(String(key))}
          />
        </div>
        {!collapsed ? (
          <div className="admin-shell-sider-footer">
            <Tag color="blue">{roleLabels[role]}</Tag>
            <Tag color="cyan">{presentUserName(user)}</Tag>
          </div>
        ) : null}
      </Sider>

      <Layout>
        <Header className="admin-shell-header">
          <div className="admin-shell-header-left">
            <Button
              type="text"
              className="admin-shell-trigger"
              icon={collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
              onClick={() => setCollapsed(prev => !prev)}
            />
            <div className="admin-shell-page-meta">
              <Text className="admin-shell-page-kicker">Career OS</Text>
              <Title level={5} className="admin-shell-page-title">{selected?.label || 'Dashboard'}</Title>
            </div>
          </div>

          <Space size={12}>
            <Button type="default" onClick={() => { setGuideStep(0); setGuideOpen(true) }}>
              操作引导
            </Button>
            <Button
              type="text"
              className="admin-shell-tool-btn"
              icon={isFullscreen ? <FullscreenExitOutlined /> : <FullscreenOutlined />}
              onClick={toggleFullscreen}
            />
            <Dropdown
              menu={{
                items: accountMenuItems,
                onClick: ({ key }) => {
                  if (key === 'logout') {
                    void doLogout()
                  }
                }
              }}
              trigger={['click']}
            >
              <Button className="admin-shell-account-btn">{presentUserName(user)}</Button>
            </Dropdown>
          </Space>
        </Header>

        <Content className="app-body admin-shell-content">
          <div className="page-hero-card admin-shell-hero" ref={pageHeroRef}>
            <div>
              <Title level={2} className="page-title">{selected?.label || '工作台'}</Title>
              <Text className="page-description">{pageDescriptions[selectedKey] || '业务工作台'}</Text>
            </div>
            <div className="admin-shell-hero-side" ref={capabilityRef}>
              <Tag color="geekblue">{roleLabels[role]}</Tag>
              <Text className="admin-shell-hero-capability">{roleCapabilityTexts[role].join(' / ')}</Text>
            </div>
          </div>
          {children}
        </Content>
      </Layout>
      <Tour
        open={guideOpen}
        current={guideStep}
        steps={tourSteps as any}
        onChange={(current) => setGuideStep(current)}
        closeIcon={<span className="guide-skip-link">跳过</span>}
        onClose={() => {
          setGuideOpen(false)
          localStorage.setItem(GUIDE_SEEN_KEY, '1')
        }}
      />
    </Layout>
  )
}
