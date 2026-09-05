import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'
import { App, Button, Form, Input, Tabs } from 'antd'
import { ApartmentOutlined, LockOutlined, ReloadOutlined, UserOutlined } from '@ant-design/icons'
import { useAuth } from '../auth/AuthContext'
import { api } from '../api/client'
import '../styles/login.css'

type Credentials = { username: string; password: string; captcha?: string }
type Captcha = { captcha_id: string; image: string }

export default function Login() {
  const { message } = App.useApp()
  const navigate = useNavigate()
  const location = useLocation()
  const { user, loading, login, register } = useAuth()
  const [form] = Form.useForm<Credentials>()
  const [mode, setMode] = useState('login')
  const [submitting, setSubmitting] = useState(false)
  const [captcha, setCaptcha] = useState<Captcha | null>(null)
  const [captchaLoading, setCaptchaLoading] = useState(false)
  const captchaRequest = useRef(0)
  const registering = mode === 'register'

  const nextPath = useMemo(() => {
    const next = new URLSearchParams(location.search).get('next') || '/'
    return next.startsWith('/') && !next.startsWith('//') && !next.startsWith('/login') ? next : '/'
  }, [location.search])

  const loadCaptcha = useCallback(async () => {
    const request = ++captchaRequest.current
    setCaptchaLoading(true)
    setCaptcha(null)
    form.setFieldsValue({ captcha: '' })
    try {
      const res = await api.get('/auth/captcha', { timeout: 15000 })
      if (request === captchaRequest.current) setCaptcha(res.data)
    } catch {
      if (request === captchaRequest.current) message.error('验证码加载失败，请点击重试')
    } finally {
      if (request === captchaRequest.current) setCaptchaLoading(false)
    }
  }, [form, message])

  useEffect(() => {
    if (registering) void loadCaptcha()
    return () => { captchaRequest.current += 1 }
  }, [registering, loadCaptcha])

  useEffect(() => {
    if (!loading && user) navigate(nextPath, { replace: true })
  }, [loading, user, nextPath, navigate])

  if (!loading && user) return <Navigate to={nextPath} replace />

  const onFinish = async (values: Credentials) => {
    setSubmitting(true)
    try {
      if (registering) {
        if (!captcha) { message.error('请先获取验证码'); return }
        await register(values.username.trim(), values.password, captcha.captcha_id, values.captcha || '')
        message.success('注册成功')
      } else {
        await login(values.username.trim(), values.password)
      }
      navigate(nextPath, { replace: true })
    } catch (error: any) {
      const code = error?.response?.data?.detail || ''
      const messages: Record<string, string> = {
        invalid_credentials: '用户名或密码错误', user_disabled: '该账号已停用，请联系管理员',
        username_exists: '该用户名已注册，请换一个用户名或直接登录',
        username_too_short: '用户名至少需要 3 个字符', password_too_short: '密码至少需要 6 个字符',
        captcha_required: '请填写图形验证码', captcha_invalid: '验证码不正确，请重新输入',
        captcha_expired: '验证码已过期，请重新输入',
      }
      message.error(messages[code] || (error?.response ? '服务暂时不可用，请稍后重试' : '无法连接服务，请稍后重试'))
      if (registering) void loadCaptcha()
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <main className="industrial-login">
      <aside className="industrial-login-overview" aria-label="平台介绍">
        <div className="industrial-login-visual">
          <img src="/images/login-resume.svg" alt="个人简历与职业档案插画" />
          <h1>从了解自己，到规划未来</h1>
          <p>整理个人经历，发现适合的岗位，<br />制定清晰的职业行动计划。</p>
          <div className="industrial-login-overview-foot"><span>学生画像</span><span>岗位匹配</span><span>职业规划</span></div>
        </div>
      </aside>
      <div className="industrial-login-main">
        <header className="industrial-login-topbar">
          <div className="industrial-login-brand"><span className="industrial-login-mark"><ApartmentOutlined /></span><strong>职途 Agent</strong><span className="industrial-login-brand-divider" /><span>高校精准就业平台</span></div>
          <span className="industrial-login-topbar-note">职业规划工作台</span>
        </header>
        <div className="industrial-login-stage">
          <section className="industrial-login-access" aria-label="账号访问">
            <div className="industrial-login-access-heading"><h2>{registering ? '注册' : '登录'}</h2><p>{registering ? '创建职途账号，开启职业规划' : '请使用职途账号进行登录'}</p></div>
            <Tabs className="industrial-login-tabs" activeKey={mode} onChange={key => { if (!submitting) { setMode(key); form.setFields([{ name: 'username', errors: [] }, { name: 'password', errors: [] }, { name: 'captcha', errors: [] }]) } }} items={[{ key: 'login', label: '登录', disabled: submitting }, { key: 'register', label: '注册', disabled: submitting }]} />
            <Form form={form} layout="vertical" onFinish={onFinish} className="industrial-login-form" requiredMark={false} disabled={submitting}>
              <Form.Item label="用户名" name="username" rules={[{ required: true, whitespace: true, message: '请输入用户名' }, ...(registering ? [{ min: 3, message: '用户名至少需要 3 个字符' }] : [])]}>
                <Input prefix={<UserOutlined />} autoComplete="username" placeholder={registering ? '设置用户名，至少 3 个字符' : '请输入用户名'} size="large" />
              </Form.Item>
              <Form.Item label="密码" name="password" rules={[{ required: true, message: '请输入密码' }, ...(registering ? [{ min: 6, message: '密码至少需要 6 个字符' }] : [])]}>
                <Input.Password prefix={<LockOutlined />} autoComplete={registering ? 'new-password' : 'current-password'} placeholder={registering ? '设置密码，至少 6 个字符' : '请输入密码'} size="large" />
              </Form.Item>
              {registering && <Form.Item label="图形验证码" required>
                <div className="industrial-login-captcha-row">
                  <Form.Item name="captcha" noStyle rules={[{ required: true, message: '请输入验证码' }, { pattern: /^[a-zA-Z]{4}$/, message: '请输入图片中的 4 位字母' }]}>
                    <Input aria-label="图形验证码" placeholder="4 位字母" maxLength={4} autoComplete="off" autoCapitalize="characters" spellCheck={false} size="large" />
                  </Form.Item>
                  <button type="button" className="industrial-login-captcha" onClick={() => void loadCaptcha()} disabled={captchaLoading || submitting} aria-label="刷新图形验证码" title="点击换一张验证码">
                    {captcha && !captchaLoading ? <img src={captcha.image} alt="四位字母图形验证码" /> : <span>{captchaLoading ? '加载中…' : '点击重试'}</span>}
                  </button>
                </div>
                <div className="industrial-login-captcha-hint"><span>字母不区分大小写</span><button type="button" onClick={() => void loadCaptcha()} disabled={captchaLoading || submitting}><ReloadOutlined /> 换一张</button></div>
              </Form.Item>}
              <Button type="primary" htmlType="submit" block loading={submitting} disabled={registering && (!captcha || captchaLoading)} size="large" className="industrial-login-submit">{registering ? '注册并进入平台' : '登录'}</Button>
            </Form>
            <div className="industrial-login-access-footer">{registering ? '已有账号？' : '还没有账号？'}<button type="button" disabled={submitting} onClick={() => setMode(registering ? 'login' : 'register')}>{registering ? '返回登录' : '注册账号'}</button></div>
          </section>
        </div>
        <footer className="industrial-login-footer">职途 Agent · 高校精准就业平台</footer>
      </div>
    </main>
  )
}
