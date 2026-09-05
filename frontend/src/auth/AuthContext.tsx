import React, { createContext, useContext, useEffect, useMemo, useState } from 'react'
import { api } from '../api/client'
import { setStorageOwner } from '../utils/personalStorage'

export type UserRole = 'admin' | 'operator' | 'viewer' | 'student'

export type AuthUser = {
  user_id: string
  username: string
  display_name?: string
  role: UserRole
  is_active: boolean
}

type AuthContextValue = {
  user: AuthUser | null
  loading: boolean
  isAdmin: boolean
  canWrite: boolean
  hasRole: (roles: UserRole[]) => boolean
  refresh: () => Promise<AuthUser | null>
  login: (username: string, password: string) => Promise<AuthUser>
  register: (username: string, password: string, captchaId: string, captcha: string) => Promise<AuthUser>
  logout: () => Promise<void>
}

const AuthContext = createContext<AuthContextValue | null>(null)

function normalizeRole(raw: unknown): UserRole {
  const role = String(raw || '').trim().toLowerCase()
  if (role === 'admin' || role === 'operator' || role === 'viewer' || role === 'student') return role
  return 'viewer'
}

function normalizeUser(raw: any): AuthUser | null {
  if (!raw || typeof raw !== 'object') return null
  const userId = String(raw?.user_id || '').trim()
  const username = String(raw?.username || '').trim()
  if (!userId || !username) return null
  return {
    user_id: userId,
    username,
    display_name: raw?.display_name ? String(raw.display_name) : undefined,
    role: normalizeRole(raw?.role),
    is_active: !!raw?.is_active
  }
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null)
  const [loading, setLoading] = useState(true)

  const refresh = async () => {
    try {
      const res = await api.get('/auth/me')
      const next = normalizeUser(res.data?.user)
      setStorageOwner(next?.user_id || '')
      setUser(next)
      return next
    } catch {
      setStorageOwner('')
      setUser(null)
      return null
    } finally {
      setLoading(false)
    }
  }

  const login = async (username: string, password: string) => {
    const res = await api.post('/auth/login', { username, password })
    const next = normalizeUser(res.data?.user)
    if (!next) throw new Error('invalid_login_response')
    setStorageOwner(next.user_id)
    setUser(next)
    return next
  }

  const register = async (username: string, password: string, captchaId: string, captcha: string) => {
    const res = await api.post('/auth/register', { username, password, captcha_id: captchaId, captcha })
    const next = normalizeUser(res.data?.user)
    if (!next) throw new Error('invalid_register_response')
    setStorageOwner(next.user_id)
    setUser(next)
    return next
  }

  const logout = async () => {
    try {
      await api.post('/auth/logout')
    } finally {
      setStorageOwner('')
      setUser(null)
    }
  }

  useEffect(() => {
    void refresh()
    const syncAccount = (event: StorageEvent) => {
      if (event.key === 'career_storage_owner') void refresh()
    }
    window.addEventListener('storage', syncAccount)
    return () => window.removeEventListener('storage', syncAccount)
  }, [])

  const value = useMemo<AuthContextValue>(() => {
    const role = user?.role || 'viewer'
    return {
      user,
      loading,
      isAdmin: role === 'admin',
      canWrite: role === 'admin' || role === 'operator' || role === 'student',
      hasRole: (roles: UserRole[]) => !!user && roles.includes(role),
      refresh,
      login,
      register,
      logout
    }
  }, [user, loading])

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
