import React from 'react'
import { taskBadgeClass, methodBadgeClass } from '../utils/format'

export function StatusBadge({ status }: { status?: string }) {
  return <span className={`badge ${taskBadgeClass(status)}`}>{status || 'UNKNOWN'}</span>
}

export function MethodBadge({ method }: { method: string }) {
  return <span className={`badge ${methodBadgeClass(method)}`}>{method.toUpperCase()}</span>
}
