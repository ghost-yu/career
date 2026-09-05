import React from 'react'
import { Empty } from 'antd'
import { RightOutlined } from '@ant-design/icons'

type NodeLabelFn = (node: any) => string

function defaultNodeLabel(node: any): string {
  if (typeof node === 'string') return node
  return String(node?.title || node?.name || node?.role_name || node?.role_id || '').trim() || '未知节点'
}

function normalizePath(path: any): any[] {
  if (Array.isArray(path?.nodes)) return path.nodes
  if (Array.isArray(path)) return path
  return []
}

type PathFlowProps = {
  nodes: any[]
  nodeLabel?: NodeLabelFn
  emptyText?: string
  className?: string
  compact?: boolean
}

export function PathFlow({
  nodes,
  nodeLabel = defaultNodeLabel,
  emptyText = '暂无路径',
  className = '',
  compact = false
}: PathFlowProps) {
  const items = (nodes || []).filter(Boolean)
  if (!items.length) {
    return <Empty description={emptyText} image={Empty.PRESENTED_IMAGE_SIMPLE} />
  }

  return (
    <div className={`cpv-flow ${compact ? 'cpv-flow-compact' : ''} ${className}`.trim()}>
      {items.map((node: any, idx: number) => (
        <React.Fragment key={`${idx}-${node?.role_id || node?.job_id || node?.title || node?.name || ''}`}>
          <div className={`cpv-node ${idx === 0 ? 'cpv-node-source' : idx === items.length - 1 ? 'cpv-node-target' : ''}`}>
            {nodeLabel(node)}
          </div>
          {idx < items.length - 1 ? <RightOutlined className="cpv-arrow" /> : null}
        </React.Fragment>
      ))}
    </div>
  )
}

type PathFlowListProps = {
  paths: any[]
  nodeLabel?: NodeLabelFn
  emptyText?: string
  maxCount?: number
  compact?: boolean
}

export function PathFlowList({
  paths,
  nodeLabel = defaultNodeLabel,
  emptyText = '暂无路径',
  maxCount = 4,
  compact = false
}: PathFlowListProps) {
  const list = (paths || []).slice(0, maxCount)
  if (!list.length) {
    return <Empty description={emptyText} image={Empty.PRESENTED_IMAGE_SIMPLE} />
  }

  return (
    <div className="cpv-list">
      {list.map((path: any, idx: number) => (
        <div key={idx} className="cpv-list-item">
          <PathFlow
            nodes={normalizePath(path)}
            nodeLabel={nodeLabel}
            emptyText={emptyText}
            compact={compact}
          />
        </div>
      ))}
    </div>
  )
}
