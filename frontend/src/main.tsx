import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter, Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { App, ConfigProvider, Spin, theme } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import { AuthProvider, useAuth, UserRole } from './auth/AuthContext'
import { AppShell } from './components/AppShell'
import Login from './pages/Login'
import Dashboard from './pages/Dashboard'
import Jobs from './pages/Jobs'
import StudentWorkspace from './pages/StudentWorkspace'
import MatchWorkbench from './pages/MatchWorkbench'
import Roles from './pages/Roles'
import Assistant from './pages/Assistant'
import ReportStudio from './pages/ReportStudio'
import Operations from './pages/Operations'
import AccuracyLab from './pages/AccuracyLab'
import ResumeStudio from './pages/ResumeStudio'
import ResumeTemplateEditor from './pages/ResumeTemplateEditor'
import DefenseScreen from './pages/DefenseScreen'
import InterviewCoach from './pages/InterviewCoach'
import InterviewCodingTest from './pages/InterviewCodingTest'
import InterviewFaceAuth from './pages/InterviewFaceAuth'
import './styles/global.css'
import './styles/beautify.css'
import './styles/career-path-viz.css'
import './styles/career-roadmap-graph.css'

function ProtectedRoute({ children, roles }: { children: React.ReactNode; roles?: UserRole[] }) {
  const location = useLocation()
  const { user, loading, hasRole } = useAuth()

  if (loading) {
    return (
      <div className="route-loading">
        <Spin size="large" />
      </div>
    )
  }
  if (!user) {
    const next = encodeURIComponent(`${location.pathname}${location.search}`)
    return <Navigate to={`/login?next=${next}`} replace />
  }
  if (roles && !hasRole(roles)) {
    return <Navigate to="/" replace />
  }
  return <React.Fragment key={user.user_id}>{children}</React.Fragment>
}

function ShellPage({ children, roles }: { children: React.ReactNode; roles?: UserRole[] }) {
  return (
    <ProtectedRoute roles={roles}>
      <AppShell>{children}</AppShell>
    </ProtectedRoute>
  )
}

function AppRouter() {
  return (
    <AuthProvider>
      <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/" element={<ShellPage><Dashboard /></ShellPage>} />
          <Route path="/jobs" element={<ShellPage><Jobs /></ShellPage>} />
          <Route path="/student" element={<ShellPage><StudentWorkspace /></ShellPage>} />
          <Route path="/match" element={<ShellPage><MatchWorkbench /></ShellPage>} />
          <Route path="/roles" element={<ShellPage><Roles /></ShellPage>} />
          <Route path="/assistant" element={<ShellPage><Assistant /></ShellPage>} />
          <Route path="/interview" element={<ShellPage><InterviewCoach /></ShellPage>} />
          <Route path="/interview/coding" element={<ShellPage><InterviewCodingTest /></ShellPage>} />
          <Route path="/interview/face" element={<ShellPage><InterviewFaceAuth /></ShellPage>} />
          <Route path="/news" element={<Navigate to="/" replace />} />
          <Route path="/defense-screen" element={<ProtectedRoute><DefenseScreen /></ProtectedRoute>} />
          <Route path="/resume/editor" element={<ProtectedRoute><ResumeTemplateEditor /></ProtectedRoute>} />
          <Route path="/resume" element={<ShellPage><ResumeStudio /></ShellPage>} />
          <Route path="/advisor" element={<Navigate to="/assistant" replace />} />
          <Route path="/report" element={<ShellPage><ReportStudio /></ShellPage>} />
          <Route path="/operations" element={<ShellPage roles={['admin']}><Operations /></ShellPage>} />
          <Route path="/accuracy-lab" element={<ShellPage roles={['admin']}><AccuracyLab /></ShellPage>} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  )
}

function RootApp() {
  return (
    <ConfigProvider
      locale={zhCN}
      theme={{
        algorithm: theme.defaultAlgorithm,
        token: {
          colorPrimary: '#1677ff',
          colorInfo: '#1677ff',
          colorSuccess: '#52c41a',
          colorWarning: '#faad14',
          colorError: '#ff4d4f',
          borderRadius: 6,
          borderRadiusLG: 8,
          borderRadiusSM: 4,
          fontSize: 14,
          fontFamily: `-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, 'Noto Sans', sans-serif, 'Apple Color Emoji', 'Segoe UI Emoji', 'Segoe UI Symbol', 'Noto Color Emoji'`,
          boxShadow: '0 1px 2px 0 rgba(0, 0, 0, 0.03), 0 1px 6px -1px rgba(0, 0, 0, 0.02), 0 2px 4px 0 rgba(0, 0, 0, 0.02)',
          colorBgLayout: '#f0f2f5'
        }
      }}
    >
      <App>
        <AppRouter />
      </App>
    </ConfigProvider>
  )
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <RootApp />
  </React.StrictMode>
)
