import React from 'react'

export function SectionCard({
  title,
  subtitle,
  actions,
  children,
  className = ''
}: {
  title: string
  subtitle?: string
  actions?: React.ReactNode
  children: React.ReactNode
  className?: string
}) {
  return (
    <section className={`card section-card ${className}`.trim()}>
      <div className="card-header section-card-header">
        <div>
          <h3 className="card-title">{title}</h3>
          {subtitle ? <div className="section-card-subtitle">{subtitle}</div> : null}
        </div>
        {actions ? <div className="section-card-actions">{actions}</div> : null}
      </div>
      <div className="card-body">{children}</div>
    </section>
  )
}
