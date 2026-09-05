import React from 'react'

export function CodePanel({ children }: { children: React.ReactNode }) {
  return (
    <pre className="code-panel">
      {children}
    </pre>
  )
}
