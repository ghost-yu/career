import axios from 'axios'

function inferApiBase() {
  if (typeof window !== 'undefined') {
    const protocol = window.location.protocol === 'https:' ? 'https' : 'http'
    const hostname = window.location.hostname || 'localhost'
    // Keep frontend and backend on same host (127.0.0.1 vs localhost) to avoid auth cookie mismatch.
    return `${protocol}://${hostname}:8000`
  }
  return 'http://localhost:8000'
}

const envBase = String((import.meta as any).env?.VITE_API_BASE || '').trim()
const rawBase = envBase || inferApiBase()

export const api = axios.create({
  baseURL: rawBase.replace(/\/$/, ''),
  timeout: 300000,
  withCredentials: true
})

api.interceptors.response.use(
  (resp) => resp,
  (error) => {
    const status = Number(error?.response?.status || 0)
    const url = String(error?.config?.url || '')
    if (status === 401 && typeof window !== 'undefined') {
      const isLoginReq = url.includes('/auth/login')
      const isLoginPage = window.location.pathname.startsWith('/login')
      if (!isLoginReq && !isLoginPage) {
        const next = encodeURIComponent(`${window.location.pathname}${window.location.search}`)
        window.location.href = `/login?next=${next}`
      }
    }
    return Promise.reject(error)
  }
)

export function apiUrl(path: string) {
  const normalized = path.startsWith('/') ? path : `/${path}`
  return `${api.defaults.baseURL}${normalized}`
}
