export type SimpleUser = {
  username?: string
  display_name?: string
  role?: string
}

const USERNAME_ALIAS: Record<string, string> = {
  admin: '平台主管',
  operator01: '就业老师',
  viewer01: '展示账号',
  '管理员': '平台主管',
  '就业老师': '就业老师',
  '展示账号': '展示账号'
}

export function presentUserName(user?: SimpleUser | null) {
  if (!user) return '未登录账号'
  const displayName = String(user.display_name || '').trim()
  if (displayName) return displayName
  const username = String(user.username || '').trim()
  return USERNAME_ALIAS[username] || username || '未命名账号'
}

export function presentStudentName(student?: any, index?: number) {
  const name = String(student?.name || '').trim()
  if (name) return name
  const order = Number.isFinite(index as number) ? Number(index) + 1 : ''
  return order ? `学生档案 ${order}` : '学生档案'
}

export function presentStudentOption(student?: any, index?: number) {
  const name = presentStudentName(student, index)
  const family = String(student?.major || student?.department || '').trim()
  return family ? `${name} · ${family}` : name
}

export function presentRoleName(role?: any, index?: number) {
  const title = String(role?.title || role?.title_rep || role?.base_role || '').trim()
  if (title) return title
  const order = Number.isFinite(index as number) ? Number(index) + 1 : 0
  return order ? `职业方向 ${order}` : '职业方向'
}

export function presentJobName(job?: any, index?: number) {
  const title = String(job?.title || '').trim()
  if (title) return title
  const order = Number.isFinite(index as number) ? Number(index) + 1 : 0
  return order ? `岗位样本 ${order}` : '岗位样本'
}

export function presentReportLabel(report?: any, index?: number) {
  const roleName = String(report?.target_role_title || report?.role_title || report?.career_path?.target_role || '').trim()
  const version = Number(report?.version || 0)
  const order = Number.isFinite(index as number) ? Number(index) + 1 : 0
  const base = roleName || (order ? `职业规划报告 ${order}` : '职业规划报告')
  return version > 0 ? `${base} · 第 ${version} 版` : base
}

export function presentTaskStatus(status?: string) {
  const key = String(status || '').trim().toUpperCase()
  if (key === 'SUCCESS') return '已完成'
  if (key === 'FAILED') return '失败'
  if (key === 'RUNNING') return '执行中'
  if (key === 'PENDING') return '待执行'
  return '未知状态'
}

export function presentTaskType(taskType?: string) {
  const raw = String(taskType || '').trim().toLowerCase()
  const map: Record<string, string> = {
    ingest_file: '岗位数据入仓',
    full_rebuild: '全量重建',
    rebuild_roles: '角色图谱重建',
    rebuild_graph: '图谱重建',
    rebuild_kb: '知识库重建',
    synthetic_students: '样本学生生成',
    llm_verify: '模型链路校验'
  }
  return map[raw] || (raw ? raw.replace(/_/g, ' ') : '未命名任务')
}

export function presentSeverity(value?: string) {
  const raw = String(value || '').trim().toLowerCase()
  if (raw === 'high') return '高'
  if (raw === 'medium') return '中'
  if (raw === 'low') return '低'
  return '常规'
}

export function presentIssueType(value?: string) {
  const raw = String(value || '').trim().toLowerCase()
  if (raw === 'plain') return '普通问题'
  if (raw === 'rule') return '规则校验'
  return raw ? raw : '规则校验'
}


export function presentEventType(value?: string) {
  const raw = String(value || '').trim().toUpperCase()
  const map: Record<string, string> = {
    SEARCH: '搜索行为',
    VIEW_ROLE: '查看方向',
    VIEW_JOB: '查看岗位',
    GENERATE_REPORT: '生成报告',
    ASK_AGENT: '顾问问答',
    MATCH_SCORE: '匹配评分'
  }
  return map[raw] || '行为记录'
}

export function presentEventSource(value?: string) {
  const raw = String(value || '').trim().toLowerCase()
  const map: Record<string, string> = {
    dashboard: '首页总览',
    assistant: '生涯顾问',
    advisor: '生涯顾问',
    jobs_page: '岗位洞察',
    match_workbench: '匹配诊断',
    report_studio: '报告中心'
  }
  return map[raw] || '业务页面'
}
