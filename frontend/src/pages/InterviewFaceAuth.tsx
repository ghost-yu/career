import React from 'react'
import { Alert, Space } from 'antd'
import FaceAuthPanel from '../components/FaceAuthPanel'
import { useAuth } from '../auth/AuthContext'

export default function InterviewFaceAuth() {
  const { canWrite } = useAuth()

  return (
    <Space direction="vertical" size={18} style={{ width: '100%' }}>
      {!canWrite ? <Alert type="info" showIcon message="当前账号为只读角色，可查看人脸认证页面，但不可提交认证。" /> : null}
      <FaceAuthPanel title="人脸识别认证" />
    </Space>
  )
}
