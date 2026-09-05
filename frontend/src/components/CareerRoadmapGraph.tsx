import React, { useMemo, useState } from 'react'
import { Button, Segmented, Space, Tag, Typography } from 'antd'
import { NodeIndexOutlined } from '@ant-design/icons'

const { Text, Title } = Typography

type StageKey = 'beginner' | 'intermediate' | 'advanced'
type TrackKey = 'frontend' | 'backend' | 'data_ai' | 'test_qa' | 'ops' | 'product'

type Group = {
  title: string
  topics: string[]
}

const STAGE_LABEL: Record<StageKey, string> = {
  beginner: '初阶',
  intermediate: '中阶',
  advanced: '高阶'
}

const TRACK_LABEL: Record<TrackKey, string> = {
  frontend: '前端开发',
  backend: '后端开发',
  data_ai: '数据与AI',
  test_qa: '测试质量',
  ops: '运维云原生',
  product: '产品方向'
}

const ROADMAP_GROUPS: Record<TrackKey, Record<StageKey, Group[]>> = {
  frontend: {
    beginner: [
      { title: '页面结构', topics: ['HTML', 'CSS', '语义化', '响应式'] },
      { title: '语言基础', topics: ['JavaScript', 'TypeScript', 'ES Module', '异步'] },
      { title: '浏览器机制', topics: ['DOM', '事件', '渲染流程', '缓存'] },
      { title: '接口通信', topics: ['HTTP', 'Fetch', 'JWT', 'CORS'] },
      { title: '工程工具', topics: ['Git', 'npm', 'Vite', '调试工具'] },
      { title: '基础框架', topics: ['React', '状态管理', '路由', '组件化'] },
      { title: '质量保障', topics: ['ESLint', 'Prettier', '单测', 'E2E'] },
      { title: '性能基础', topics: ['代码分割', '资源压缩', '首屏优化', 'CDN'] }
    ],
    intermediate: [
      { title: '框架进阶', topics: ['Hooks', 'Context', '高阶组件', '渲染模式'] },
      { title: '中台能力', topics: ['Design System', '组件库', '权限模型', '微前端'] },
      { title: '构建链路', topics: ['Webpack/Vite', 'Babel/ESBuild', 'CI/CD', 'Monorepo'] },
      { title: '稳定性', topics: ['错误监控', '埋点分析', '灰度发布', '回滚'] },
      { title: '可视化', topics: ['Canvas', 'SVG', 'ECharts', '交互图谱'] },
      { title: '服务协同', topics: ['BFF', 'API 设计', '网关协作', '契约测试'] },
      { title: '业务抽象', topics: ['领域建模', '流程编排', '低代码扩展', '配置化'] },
      { title: '体验设计', topics: ['无障碍', '动效系统', '多端适配', '国际化'] }
    ],
    advanced: [
      { title: '平台化', topics: ['研发平台', '脚手架生态', '代码生成', '规范中心'] },
      { title: '高性能', topics: ['渲染优化', '运行时调度', '内存诊断', '端性能治理'] },
      { title: '跨端体系', topics: ['Web/小程序', 'Hybrid', '跨端组件', '一致性策略'] },
      { title: '智能前端', topics: ['AI 辅助研发', '智能表单', '智能可视化', 'AIOps联动'] },
      { title: '架构治理', topics: ['分层架构', '依赖治理', '可观测性', '风险预警'] },
      { title: '业务中枢', topics: ['运营中台', '决策看板', '实时分析', '自动化运营'] },
      { title: '全链路质量', topics: ['质量门禁', '压测演练', '故障复盘', 'SLO'] },
      { title: '技术影响力', topics: ['方案评审', '技术布道', '人才培养', '开源协作'] }
    ]
  },
  backend: {
    beginner: [
      { title: '语言与框架', topics: ['Python/Java/Go', 'FastAPI/Spring', 'REST API', '异常处理'] },
      { title: '数据存储', topics: ['MySQL', 'Redis', '索引', '事务'] },
      { title: '服务基础', topics: ['认证鉴权', '日志', '配置管理', '参数校验'] },
      { title: '工程能力', topics: ['Git Flow', '测试', '代码规范', '文档'] },
      { title: '通信协议', topics: ['HTTP', 'gRPC', '消息队列', '序列化'] },
      { title: '部署运行', topics: ['Linux', 'Docker', '进程管理', '健康检查'] },
      { title: '安全基础', topics: ['SQL注入防护', '权限控制', '限流', '审计'] },
      { title: '排障能力', topics: ['日志定位', '链路追踪', '性能剖析', '根因分析'] }
    ],
    intermediate: [
      { title: '架构设计', topics: ['分层架构', 'DDD', '服务拆分', '网关'] },
      { title: '高并发', topics: ['缓存策略', '队列削峰', '并发控制', '降级熔断'] },
      { title: '数据治理', topics: ['分库分表', '读写分离', '数据一致性', '迁移'] },
      { title: '可观测性', topics: ['Metrics', 'Tracing', '告警', '仪表盘'] },
      { title: '稳定性工程', topics: ['灰度', '回滚', '压测', '容灾'] },
      { title: '平台协同', topics: ['CI/CD', '环境管理', '制品管理', '自动发布'] },
      { title: '安全治理', topics: ['风控', '密钥管理', '漏洞修复', '合规'] },
      { title: '跨团队协作', topics: ['接口契约', 'SLA', '需求评审', '变更管理'] }
    ],
    advanced: [
      { title: '平台架构', topics: ['服务网格', '事件驱动', '多租户', '中台能力'] },
      { title: '全球化部署', topics: ['多区域', '多活架构', '流量调度', '容灾演练'] },
      { title: '成本优化', topics: ['容量规划', '冷热分层', '弹性扩缩', '成本监控'] },
      { title: '智能运维协同', topics: ['异常检测', '自动扩缩容', '策略编排', '自愈'] },
      { title: '数据平台融合', topics: ['实时计算', '离线计算', '数据服务', '数据资产'] },
      { title: '架构治理', topics: ['技术债治理', '生命周期管理', '标准化', '质量看板'] },
      { title: '业务连续性', topics: ['灾备切换', '演练体系', '应急预案', '复盘机制'] },
      { title: '组织影响力', topics: ['技术战略', '团队建设', '效率体系', '工程文化'] }
    ]
  },
  data_ai: {
    beginner: [
      { title: '数据基础', topics: ['SQL', '统计学', '数据清洗', '特征理解'] },
      { title: '分析工具', topics: ['Python', 'Pandas', 'Notebook', '可视化'] },
      { title: '机器学习', topics: ['监督学习', '模型评估', '交叉验证', '调参'] },
      { title: 'AI 工程', topics: ['向量检索', 'Embedding', 'RAG', 'Prompt'] },
      { title: '数据工程', topics: ['ETL', '数据仓库', '批处理', '任务调度'] },
      { title: '模型上线', topics: ['模型服务', 'A/B 测试', '效果监控', '回滚'] },
      { title: '治理合规', topics: ['数据脱敏', '权限控制', '审计', '合规'] },
      { title: '业务理解', topics: ['指标体系', '实验设计', '洞察表达', '复盘'] }
    ],
    intermediate: [
      { title: '推荐与检索', topics: ['召回排序', '特征工程', '重排', '在线学习'] },
      { title: 'LLM 应用', topics: ['Agent', 'ToolUse', '多轮记忆', '评测体系'] },
      { title: '数据平台', topics: ['湖仓一体', '流批一体', '元数据', '质量监控'] },
      { title: 'MLOps', topics: ['训练流水线', '模型版本', '自动部署', '监控告警'] },
      { title: '系统优化', topics: ['推理加速', '缓存策略', '延迟优化', '成本控制'] },
      { title: '可解释性', topics: ['特征贡献', '偏差分析', '错误归因', '人审机制'] },
      { title: '业务闭环', topics: ['目标拆解', '策略迭代', '实验平台', '增长联动'] },
      { title: '质量评测', topics: ['离线评测', '在线评测', '鲁棒性', '安全评估'] }
    ],
    advanced: [
      { title: '模型平台化', topics: ['多模型路由', '模型编排', '统一网关', '策略控制'] },
      { title: '智能决策', topics: ['强化学习', '因果推断', '实时决策', '闭环优化'] },
      { title: '企业知识系统', topics: ['知识图谱', '语义检索', '知识更新', '可信引用'] },
      { title: '高可用AI服务', topics: ['弹性推理', '多集群', '容错降级', '稳定性'] },
      { title: 'AI 安全治理', topics: ['内容安全', '越狱防护', '隐私保护', '风险审计'] },
      { title: '数据资产化', topics: ['数据产品', '价值评估', '资产运营', '跨域共享'] },
      { title: '组织级落地', topics: ['AI 赋能流程', '角色协同', '变革管理', 'ROI评估'] },
      { title: '前沿探索', topics: ['多模态', '自主体系统', '自动科学', '行业大模型'] }
    ]
  },
  test_qa: {
    beginner: [
      { title: '测试基础', topics: ['测试用例', '缺陷管理', '功能测试', '回归测试'] },
      { title: '自动化入门', topics: ['Selenium/Playwright', '接口自动化', '数据驱动', '报告'] },
      { title: '质量意识', topics: ['边界分析', '等价类', '风险识别', '追踪闭环'] },
      { title: '协作流程', topics: ['需求评审', '测试计划', '发布验证', '复盘'] },
      { title: '性能基础', topics: ['压测脚本', '并发模型', '瓶颈定位', '指标'] },
      { title: '工具链', topics: ['Jira', 'TestRail', 'CI 集成', '告警'] },
      { title: '安全测试', topics: ['OWASP', '漏洞验证', '权限测试', '数据安全'] },
      { title: '文档输出', topics: ['测试报告', '质量周报', '问题归因', '建议'] }
    ],
    intermediate: [
      { title: '自动化体系', topics: ['分层自动化', '稳定性治理', '夹具管理', 'Mock'] },
      { title: '持续质量', topics: ['质量门禁', '流水线检查', '变更风险', '冒烟'] },
      { title: '性能工程', topics: ['容量规划', '链路压测', '性能基线', '优化建议'] },
      { title: '质量平台', topics: ['测试平台', '数据看板', '效率度量', '覆盖率'] },
      { title: '异常防控', topics: ['故障注入', '混沌工程', '预案演练', '恢复验证'] },
      { title: '标准规范', topics: ['测试标准', '发布准入', '审计规范', '模板化'] },
      { title: '跨团队协作', topics: ['开发联动', '产品联动', '运维联动', '问题推动'] },
      { title: '业务质量', topics: ['转化漏斗', '体验质量', '核心路径', '风险热区'] }
    ],
    advanced: [
      { title: '质量战略', topics: ['组织级质量体系', '质量文化', '治理机制', '目标管理'] },
      { title: '智能测试', topics: ['AI生成用例', '异常预测', '根因定位', '自动修复建议'] },
      { title: '全链路保障', topics: ['端到端演练', '跨系统联测', '大促保障', '战情机制'] },
      { title: '平台生态', topics: ['统一质量平台', '插件扩展', '能力复用', '服务化'] },
      { title: '数据驱动决策', topics: ['质量指标体系', '健康度模型', '风险分级', '趋势预测'] },
      { title: '可靠性工程', topics: ['SRE协作', 'SLO门禁', '故障预算', '持续改进'] },
      { title: '行业合规', topics: ['审计追踪', '监管合规', '安全基线', '证据留存'] },
      { title: '影响力建设', topics: ['方法论沉淀', '培训赋能', '标准输出', '外部交流'] }
    ]
  },
  ops: {
    beginner: [
      { title: '系统基础', topics: ['Linux', 'Shell', '网络基础', '存储基础'] },
      { title: '部署交付', topics: ['Docker', 'Nginx', '发布流程', '环境配置'] },
      { title: '监控告警', topics: ['Prometheus', 'Grafana', '日志采集', '告警规则'] },
      { title: '故障处理', topics: ['值班流程', '故障定位', '应急响应', '复盘'] },
      { title: '自动化', topics: ['脚本自动化', '任务编排', '批量运维', '巡检'] },
      { title: '安全基线', topics: ['主机安全', '访问控制', '补丁管理', '备份'] },
      { title: '云服务', topics: ['云主机', '对象存储', '负载均衡', '云监控'] },
      { title: '协作能力', topics: ['变更评审', '发布协同', '容量沟通', '文档'] }
    ],
    intermediate: [
      { title: '云原生', topics: ['Kubernetes', 'Helm', 'Service Mesh', 'Ingress'] },
      { title: 'SRE 实践', topics: ['SLO/SLI', '错误预算', '容量规划', '稳定性治理'] },
      { title: '平台工程', topics: ['内部平台', '自助运维', '权限编排', '服务目录'] },
      { title: '安全运维', topics: ['零信任', '密钥管理', '合规检查', '审计'] },
      { title: '成本治理', topics: ['资源画像', '弹性策略', '成本分摊', '优化方案'] },
      { title: '高可用架构', topics: ['多可用区', '故障切换', '数据备份', '恢复演练'] },
      { title: '自动化发布', topics: ['GitOps', '蓝绿/金丝雀', '回滚策略', '发布可视化'] },
      { title: '跨团队保障', topics: ['研发联动', '测试联动', '运营联动', '战情支持'] }
    ],
    advanced: [
      { title: '平台治理', topics: ['平台产品化', '多租户', '运营指标', '服务等级'] },
      { title: 'AIOps', topics: ['智能告警', '根因分析', '自愈编排', '异常预测'] },
      { title: '全球部署', topics: ['多区域容灾', '流量调度', '边缘节点', '跨云策略'] },
      { title: '可靠性体系', topics: ['混沌工程', '韧性测试', '可靠性评分', '持续改进'] },
      { title: '安全治理', topics: ['攻防演练', '威胁检测', '安全自动化', '应急体系'] },
      { title: '成本与效率', topics: ['单位成本', '效率模型', '资源配额', '预算管理'] },
      { title: '运维中台', topics: ['配置中心', '事件中心', '知识库', '工单自动化'] },
      { title: '组织能力', topics: ['机制建设', '流程标准', '人才梯队', '经验沉淀'] }
    ]
  },
  product: {
    beginner: [
      { title: '产品基础', topics: ['用户研究', '需求分析', '竞品分析', 'PRD'] },
      { title: '流程能力', topics: ['需求管理', '优先级', '原型设计', '评审'] },
      { title: '数据意识', topics: ['核心指标', '埋点设计', '漏斗分析', 'A/B 测试'] },
      { title: '协作沟通', topics: ['研发协作', '测试协作', '运营协作', '反馈闭环'] },
      { title: '业务理解', topics: ['商业模式', '用户分层', '增长路径', '场景拆解'] },
      { title: '体验设计', topics: ['信息架构', '交互设计', '可用性', '无障碍'] },
      { title: '项目推进', topics: ['里程碑', '风险管理', '版本节奏', '验收'] },
      { title: '文档沉淀', topics: ['方案文档', '复盘文档', '知识库', '规范'] }
    ],
    intermediate: [
      { title: '增长产品', topics: ['用户增长', '转化优化', '留存提升', '活动机制'] },
      { title: '商业化', topics: ['定价策略', '变现路径', '订单流程', '支付体验'] },
      { title: '平台产品', topics: ['平台能力', '权限体系', '开放接口', '生态策略'] },
      { title: '数据驱动', topics: ['指标看板', '实验平台', '归因分析', '策略迭代'] },
      { title: '智能产品', topics: ['AI能力接入', '提示词设计', '效果评估', '安全策略'] },
      { title: '复杂项目', topics: ['跨部门协同', '多项目并行', '资源协调', '冲突解决'] },
      { title: '质量与体验', topics: ['体验治理', '性能体验', '反馈机制', '客服闭环'] },
      { title: '业务复盘', topics: ['目标复盘', '机会识别', '策略调整', '路线规划'] }
    ],
    advanced: [
      { title: '产品战略', topics: ['战略拆解', '市场布局', '产品组合', '路线图管理'] },
      { title: '组织级协同', topics: ['目标管理', '机制建设', '流程优化', '文化推动'] },
      { title: '生态构建', topics: ['开放平台', '伙伴生态', '标准制定', '合作策略'] },
      { title: 'AI原生产品', topics: ['多Agent体验', '智能工作流', '个性化服务', '可信机制'] },
      { title: '经营管理', topics: ['收益模型', '成本模型', '效率模型', '健康度'] },
      { title: '全球化产品', topics: ['本地化策略', '区域合规', '国际增长', '跨文化设计'] },
      { title: '创新孵化', topics: ['0-1探索', '最小验证', '快速试错', '规模化落地'] },
      { title: '领导力', topics: ['团队培养', '人才机制', '决策质量', '组织影响力'] }
    ]
  }
}

const NODE_POSITIONS = [
  { x: 15, y: 18 },
  { x: 36, y: 8 },
  { x: 64, y: 8 },
  { x: 85, y: 18 },
  { x: 85, y: 70 },
  { x: 64, y: 82 },
  { x: 36, y: 82 },
  { x: 15, y: 70 }
]

type CareerRoadmapGraphProps = {
  onPickKeyword?: (keyword: string) => void
  activeKeyword?: string
}

export function CareerRoadmapGraph({ onPickKeyword, activeKeyword }: CareerRoadmapGraphProps) {
  const [stage, setStage] = useState<StageKey>('beginner')
  const [track, setTrack] = useState<TrackKey>('frontend')
  const groups = useMemo(() => ROADMAP_GROUPS[track][stage], [track, stage])
  const normalizedKeyword = String(activeKeyword || '').trim().toLowerCase()

  const isTopicActive = (topic: string) => {
    if (!normalizedKeyword) return false
    return topic.toLowerCase().includes(normalizedKeyword)
  }

  const isGroupActive = (group: Group) => {
    if (!normalizedKeyword) return false
    if (group.title.toLowerCase().includes(normalizedKeyword)) return true
    return group.topics.some((topic) => topic.toLowerCase().includes(normalizedKeyword))
  }

  return (
    <div className="crg-shell">
      <div className="crg-head">
        <div>
          <Title level={4} className="crg-title">IT 多方向成长路线图 · {TRACK_LABEL[track]} · {STAGE_LABEL[stage]}</Title>
          <Text className="crg-desc">点击任意知识点可直接回填到“角色搜索”，用于快速定位相关职业方向。</Text>
        </div>
        <Space direction="vertical" size={8}>
          <Segmented
            value={track}
            onChange={(value) => setTrack(value as TrackKey)}
            options={[
              { label: '前端', value: 'frontend' },
              { label: '后端', value: 'backend' },
              { label: '数据/AI', value: 'data_ai' },
              { label: '测试', value: 'test_qa' },
              { label: '运维', value: 'ops' },
              { label: '产品', value: 'product' }
            ]}
          />
          <Segmented
            value={stage}
            onChange={(value) => setStage(value as StageKey)}
            options={[
              { label: '初阶', value: 'beginner' },
              { label: '中阶', value: 'intermediate' },
              { label: '高阶', value: 'advanced' }
            ]}
          />
        </Space>
      </div>

      <div className="crg-map" role="region" aria-label="IT多方向成长路线图图谱">
        <svg className="crg-links" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
          {groups.map((group, index) => {
            const point = NODE_POSITIONS[index % NODE_POSITIONS.length]
            return (
              <line
                key={group.title}
                x1="50"
                y1="46"
                x2={String(point.x)}
                y2={String(point.y)}
                className={`crg-link ${isGroupActive(group) ? 'active' : ''}`}
              />
            )
          })}
        </svg>

        <div className="crg-center">
          <NodeIndexOutlined />
          <div>
            <div className="crg-center-title">{TRACK_LABEL[track]}</div>
            <div className="crg-center-meta">阶段：{STAGE_LABEL[stage]} · IT职业图谱</div>
          </div>
        </div>

        {groups.map((group, index) => {
          const point = NODE_POSITIONS[index % NODE_POSITIONS.length]
          return (
            <div
              key={group.title}
              className={`crg-card ${isGroupActive(group) ? 'active' : ''}`}
              style={{ left: `${point.x}%`, top: `${point.y}%` }}
            >
              <div className="crg-card-head">
                <span className="crg-dot" />
                <Text strong>{group.title}</Text>
              </div>
              <Space size={[6, 8]} wrap>
                {group.topics.map((topic) => (
                  <Tag
                    key={topic}
                    className={`crg-topic ${isTopicActive(topic) ? 'active' : ''}`}
                    onClick={() => onPickKeyword?.(topic)}
                  >
                    {topic}
                  </Tag>
                ))}
              </Space>
              <Button size="small" type="link" onClick={() => onPickKeyword?.(group.title)}>
                用于筛选角色
              </Button>
            </div>
          )
        })}
      </div>
    </div>
  )
}
