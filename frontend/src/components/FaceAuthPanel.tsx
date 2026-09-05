import { personalStorageKey } from '../utils/personalStorage'
import React, { useEffect, useMemo, useRef, useState } from 'react'
import { Alert, App, Button, Card, Space, Tag, Typography } from 'antd'
import { CameraOutlined, CheckCircleOutlined, SafetyCertificateOutlined } from '@ant-design/icons'
import { api } from '../api/client'
import { useAuth } from '../auth/AuthContext'

const { Text } = Typography

const FACE_AUTH_STORAGE_KEY = 'interview.faceAuth.status'

type StoredFaceAuth = {
  verified: boolean
  status: string
  verifiedAt?: string
}

function readStoredFaceAuth(): StoredFaceAuth | null {
  if (typeof window === 'undefined') return null
  try {
    const raw = window.localStorage.getItem(personalStorageKey(FACE_AUTH_STORAGE_KEY))
    if (!raw) return null
    const parsed = JSON.parse(raw) as StoredFaceAuth
    return parsed && typeof parsed === 'object' ? parsed : null
  } catch {
    return null
  }
}

function presentFaceError(mode: 'register' | 'verify') {
  return mode === 'register' ? '人脸注册未完成，请重新拍照' : '身份认证未通过，请重新拍照'
}

function writeStoredFaceAuth(value: StoredFaceAuth) {
  if (typeof window === 'undefined') return
  window.localStorage.setItem(personalStorageKey(FACE_AUTH_STORAGE_KEY), JSON.stringify(value))
  window.dispatchEvent(new CustomEvent('interview-face-auth-change', { detail: value }))
}

export default function FaceAuthPanel({ compact = false, title = '人脸认证状态' }: { compact?: boolean; title?: string }) {
  const { message } = App.useApp()
  const { canWrite, user } = useAuth()
  const videoRef = useRef<HTMLVideoElement | null>(null)
  const cameraStreamRef = useRef<MediaStream | null>(null)
  const stored = useMemo(() => readStoredFaceAuth(), [])
  const [cameraOn, setCameraOn] = useState(false)
  const [faceStatus, setFaceStatus] = useState(stored?.status || '未开启摄像头')
  const [faceVerified, setFaceVerified] = useState(!!stored?.verified)
  const [verifiedAt, setVerifiedAt] = useState(stored?.verifiedAt || '')
  const [faceLoading, setFaceLoading] = useState(false)

  useEffect(() => {
    const sync = () => {
      const next = readStoredFaceAuth()
      if (!next) return
      setFaceVerified(!!next.verified)
      setFaceStatus(next.status || '认证状态已更新')
      setVerifiedAt(next.verifiedAt || '')
    }
    window.addEventListener('storage', sync)
    window.addEventListener('interview-face-auth-change', sync)
    return () => {
      window.removeEventListener('storage', sync)
      window.removeEventListener('interview-face-auth-change', sync)
      cameraStreamRef.current?.getTracks().forEach(track => track.stop())
    }
  }, [])

  const stopCamera = () => {
    cameraStreamRef.current?.getTracks().forEach(track => track.stop())
    cameraStreamRef.current = null
    if (videoRef.current) videoRef.current.srcObject = null
    setCameraOn(false)
  }

  const toggleCamera = async () => {
    if (cameraOn) {
      stopCamera()
      setFaceStatus(faceVerified ? faceStatus : '未开启摄像头')
      return
    }
    if (typeof navigator === 'undefined' || !navigator.mediaDevices?.getUserMedia) {
      message.warning('当前浏览器不支持摄像头')
      return
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: false })
      cameraStreamRef.current = stream
      if (videoRef.current) {
        videoRef.current.srcObject = stream
        await videoRef.current.play()
      }
      setCameraOn(true)
      setFaceStatus(faceVerified ? faceStatus : '摄像头已开启，待认证')
    } catch {
      message.error('无法访问摄像头，请检查浏览器权限')
    }
  }

  const captureFaceImage = () => {
    const video = videoRef.current
    if (!cameraOn || !video || !video.videoWidth || !video.videoHeight) {
      message.warning('请先开启摄像头，并确保画面已加载')
      return ''
    }
    const canvas = document.createElement('canvas')
    canvas.width = video.videoWidth
    canvas.height = video.videoHeight
    const ctx = canvas.getContext('2d')
    if (!ctx) return ''
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height)
    return canvas.toDataURL('image/jpeg', 0.9)
  }

  const submitFace = async (mode: 'register' | 'verify') => {
    if (!canWrite) {
      message.warning('只读角色不可进行人脸注册或认证')
      return
    }
    const image = captureFaceImage()
    if (!image) return
    const userId = user?.user_id || user?.username
    if (!userId) {
      message.warning('当前没有可用于认证的用户 ID')
      return
    }
    setFaceLoading(true)
    try {
      const res = await api.post(`/interview/face/${mode}`, { image, userId })
      const data = res.data || {}
      const passed = String(data.status) === '0'
      const text = String(data.message || data.msg || (passed ? '人脸认证通过' : '人脸识别失败，请重试'))
      setFaceVerified(passed)
      setFaceStatus(text)
      if (passed) {
        const at = new Date().toLocaleString()
        setVerifiedAt(at)
        writeStoredFaceAuth({ verified: true, status: text, verifiedAt: at })
        message.success(text)
      } else {
        message.warning(text)
      }
    } catch (e: any) {
      const text = presentFaceError(mode)
      setFaceVerified(false)
      setFaceStatus(text)
      message.error(text)
    } finally {
      setFaceLoading(false)
    }
  }

  return (
    <Card
      className={compact ? 'face-auth-panel face-auth-panel-compact' : 'face-auth-panel'}
      title={title}
      extra={
        <Tag icon={faceVerified ? <CheckCircleOutlined /> : <SafetyCertificateOutlined />} color={faceVerified ? 'green' : cameraOn ? 'blue' : 'default'}>
          {faceVerified ? '已认证' : '待认证'}
        </Tag>
      }
    >
      <div className={compact ? 'face-auth-layout face-auth-layout-compact' : 'face-auth-layout'}>
        <div className="face-auth-video">
          <video ref={videoRef} muted playsInline className={cameraOn ? 'is-active' : ''} />
          {!cameraOn ? <Text className="face-auth-placeholder">摄像头预览未开启</Text> : null}
        </div>
        <Space direction="vertical" size={8} className="face-auth-controls">
          <Space wrap>
            <Button icon={<CameraOutlined />} onClick={() => void toggleCamera()}>
              {cameraOn ? '关闭摄像头' : '开启摄像头'}
            </Button>
            <Button loading={faceLoading} onClick={() => void submitFace('register')} disabled={!cameraOn || !canWrite}>
              拍照注册
            </Button>
            <Button type="primary" loading={faceLoading} onClick={() => void submitFace('verify')} disabled={!cameraOn || !canWrite}>
              拍照认证
            </Button>
          </Space>
          <Text>{faceStatus}</Text>
          {verifiedAt ? <Text type="secondary">最近认证：{verifiedAt}</Text> : null}
        </Space>
      </div>
      {!compact ? (
        <Alert
          type="info"
          showIcon
          className="face-auth-note"
          message="认证状态会同步显示在模拟面试和笔试探察中"
          description="开启摄像头后可完成拍照注册与身份认证，认证状态会在面试与笔试页面持续显示。"
        />
      ) : null}
    </Card>
  )
}
