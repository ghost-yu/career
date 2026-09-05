import React from 'react'

export function MetricCard({
  label,
  value,
  hint,
  icon,
  tone = 'blue'
}: {
  label: string
  value: React.ReactNode
  hint?: string
  icon: string
  tone?: 'blue' | 'green' | 'purple' | 'orange'
}) {
  return (
    <div className={`metric-card metric-${tone}`}>
      <div>
        <div className="metric-label">{label}</div>
        <div className="metric-value">{value}</div>
        {hint ? <div className="metric-hint">{hint}</div> : null}
      </div>
      <div className="metric-icon-wrap">
        <i className={`ti ti-${icon}`} aria-hidden="true" />
      </div>
    </div>
  )
}
