import { useEffect, useMemo, useState } from 'react'
import {
  Alert,
  Badge,
  Button,
  Card,
  Checkbox,
  Col,
  Descriptions,
  Form,
  Input,
  InputNumber,
  Row,
  Select,
  Space,
  Table,
  Tag,
  Typography,
  Upload,
  message
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { UploadOutlined } from '@ant-design/icons'
import { api, apiUrl } from '../api/client'

const { Paragraph, Text, Title } = Typography

type EvalGuide = {
  skill_match_accuracy?: { target?: number }
  profile_accuracy?: { target?: number }
}

type BatchRunResult = {
  started_at?: string
  finished_at?: string
  workers?: number
  student_count?: number
  job_count?: number
  pair_count?: number
  job_profiles?: { total?: number; ok?: number; failed?: number; skipped?: number }
  student_profiles?: { total?: number; ok?: number; failed?: number; skipped?: number }
  matches?: { total?: number; ok?: number; failed?: number; skipped?: number }
}

type SourceImportResult = {
  students?: any
  jobs?: any
}

type TraceItem = {
  id: string
  at: string
  method: 'GET' | 'POST'
  path: string
  url: string
  status: number
  ok: boolean
  durationMs: number
  preview: string
}

type JobOption = {
  label: string
  value: string
}

type StudentOption = {
  label: string
  value: string
}

type SampleRow = Record<string, any>

const SAMPLE_FIELD_LABELS: Record<string, string> = {
  student_id: '学生ID',
  student_name: '学生姓名',
  job_id: '岗位ID',
  job_title: '岗位名称',
  entity_id: '实体ID',
  entity_type: '实体类型',
  field_name: '字段名',
  true_match: '人工标注匹配',
  pred_match: '系统预测匹配',
  true_value: '人工标注值',
  pred_value: '系统预测值',
  confidence: '置信度',
  reason: '说明',
  source_text: '原文片段',
  bucket: '分桶',
  error_type: '错误类型'
}

function presentFieldLabel(key: string): string {
  const zh = SAMPLE_FIELD_LABELS[key]
  return zh ? `${zh} (${key})` : key
}

function formatPercent(value: unknown): string {
  const num = Number(value)
  return Number.isFinite(num) ? `${(num * 100).toFixed(2)}%` : '-'
}

function previewText(payload: unknown, maxLen = 180): string {
  const raw = typeof payload === 'string' ? payload : JSON.stringify(payload || {})
  const clean = String(raw || '').replace(/\s+/g, ' ').trim()
  if (clean.length <= maxLen) return clean
  return `${clean.slice(0, maxLen)}...`
}

function nowTimeLabel() {
  return new Date().toLocaleString('zh-CN', { hour12: false })
}

export default function AccuracyLab() {
  const [guide, setGuide] = useState<EvalGuide>({})
  const [loadingGuide, setLoadingGuide] = useState(false)
  const [loadingEval, setLoadingEval] = useState(false)
  const [loadingBatchRun, setLoadingBatchRun] = useState(false)
  const [loadingSourceImport, setLoadingSourceImport] = useState(false)

  const [skillExportForm] = Form.useForm()
  const [profileExportForm] = Form.useForm()
  const [batchRunForm] = Form.useForm()
  const [sourceImportForm] = Form.useForm()

  const [skillEvalFile, setSkillEvalFile] = useState<File | null>(null)
  const [profileEvalFile, setProfileEvalFile] = useState<File | null>(null)
  const [resumeFiles, setResumeFiles] = useState<File[]>([])
  const [jobExcelFile, setJobExcelFile] = useState<File | null>(null)

  const [skillExportResult, setSkillExportResult] = useState<any>(null)
  const [profileExportResult, setProfileExportResult] = useState<any>(null)
  const [skillEvalResult, setSkillEvalResult] = useState<any>(null)
  const [profileEvalResult, setProfileEvalResult] = useState<any>(null)
  const [jobIdOptions, setJobIdOptions] = useState<JobOption[]>([])
  const [studentIdOptions, setStudentIdOptions] = useState<StudentOption[]>([])
  const [batchRunResult, setBatchRunResult] = useState<BatchRunResult | null>(null)
  const [sourceImportResult, setSourceImportResult] = useState<SourceImportResult | null>(null)

  const [traces, setTraces] = useState<TraceItem[]>([])

  const skillTarget = Number(guide?.skill_match_accuracy?.target ?? 0.8)
  const profileTarget = Number(guide?.profile_accuracy?.target ?? 0.9)

  const skillAccuracy = Number(skillEvalResult?.accuracy ?? NaN)
  const profileAccuracy = Number(profileEvalResult?.accuracy ?? NaN)

  const skillPass = Number.isFinite(skillAccuracy) ? skillAccuracy >= skillTarget : null
  const profilePass = Number.isFinite(profileAccuracy) ? profileAccuracy >= profileTarget : null

  const traceColumns: ColumnsType<TraceItem> = useMemo(
    () => [
      { title: '时间', dataIndex: 'at', key: 'at', width: 170 },
      { title: '方法', dataIndex: 'method', key: 'method', width: 90 },
      { title: '路径', dataIndex: 'path', key: 'path', width: 240, ellipsis: true },
      { title: '状态', dataIndex: 'status', key: 'status', width: 90 },
      {
        title: '结果',
        dataIndex: 'ok',
        key: 'ok',
        width: 100,
        render: (ok: boolean) => (ok ? <Tag color="green">成功</Tag> : <Tag color="red">失败</Tag>)
      },
      { title: '耗时(ms)', dataIndex: 'durationMs', key: 'durationMs', width: 120 },
      { title: '响应摘要', dataIndex: 'preview', key: 'preview', ellipsis: true }
    ],
    []
  )

  const skillSampleRows: SampleRow[] = Array.isArray(skillExportResult?.sample_rows) ? skillExportResult.sample_rows : []
  const profileSampleRows: SampleRow[] = Array.isArray(profileExportResult?.sample_rows) ? profileExportResult.sample_rows : []

  const buildSampleColumns = (rows: SampleRow[]): ColumnsType<SampleRow> => {
    const first = rows[0] || {}
    return Object.keys(first).map((key) => ({
      title: presentFieldLabel(key),
      dataIndex: key,
      key,
      width: 190,
      ellipsis: true
    }))
  }

  const skillSampleColumns = useMemo(() => buildSampleColumns(skillSampleRows), [skillSampleRows])
  const profileSampleColumns = useMemo(() => buildSampleColumns(profileSampleRows), [profileSampleRows])

  const pushTrace = (
    method: 'GET' | 'POST',
    path: string,
    status: number,
    ok: boolean,
    durationMs: number,
    payload: unknown
  ) => {
    const item: TraceItem = {
      id: `${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
      at: nowTimeLabel(),
      method,
      path,
      url: apiUrl(path),
      status,
      ok,
      durationMs,
      preview: previewText(payload)
    }
    setTraces((prev) => [item, ...prev].slice(0, 30))
  }

  const loadGuide = async () => {
    setLoadingGuide(true)
    const path = '/admin/eval/guide'
    const start = performance.now()
    try {
      const resp = await api.get(path)
      pushTrace('GET', path, Number(resp.status || 200), true, Math.round(performance.now() - start), resp.data)
      setGuide(resp.data || {})
    } catch (error: any) {
      const status = Number(error?.response?.status || 0)
      pushTrace('GET', path, status, false, Math.round(performance.now() - start), error?.response?.data || error?.message)
      message.error('加载评估阈值失败')
    } finally {
      setLoadingGuide(false)
    }
  }

  const loadJobs = async (keyword: string = '') => {
    const path = '/admin/jobs'
    const start = performance.now()
    try {
      const normalizedKeyword = String(keyword || '').trim()
      let items: any[] = []
      let statusCode = 200
      let pages = 1
      if (!normalizedKeyword) {
        const resp = await api.get(path, {
          params: {
            limit: 100,
            offset: 0,
          }
        })
        statusCode = Number(resp.status || 200)
        items = Array.isArray(resp.data?.items) ? resp.data.items : []
      } else {
        const pageSize = 500
        let offset = 0
        pages = 0
        while (true) {
          const resp = await api.get(path, {
            params: {
              limit: pageSize,
              offset,
              q: normalizedKeyword
            }
          })
          statusCode = Number(resp.status || 200)
          const part = Array.isArray(resp.data?.items) ? resp.data.items : []
          items.push(...part)
          pages += 1
          if (part.length < pageSize || pages >= 100) {
            break
          }
          offset += pageSize
        }
      }
      const options: JobOption[] = items.map((item: any) => ({
        label: `${String(item?.job_id || '')} | ${String(item?.title || '')}`,
        value: String(item?.job_id || '')
      })).filter((item: JobOption) => !!item.value)
      setJobIdOptions(options)
      const tracePath = normalizedKeyword
        ? `${path}?mode=full_search&q=${encodeURIComponent(normalizedKeyword)}&pages=${pages}`
        : `${path}?limit=100&offset=0`
      pushTrace('GET', tracePath, statusCode, true, Math.round(performance.now() - start), { count: options.length })
    } catch (error: any) {
      const status = Number(error?.response?.status || 0)
      const tracePath = keyword
        ? `${path}?mode=full_search&q=${encodeURIComponent(keyword)}`
        : `${path}?limit=100&offset=0`
      pushTrace('GET', tracePath, status, false, Math.round(performance.now() - start), error?.response?.data || error?.message)
    }
  }

  const loadStudents = async (keyword: string = '') => {
    const path = '/students'
    const start = performance.now()
    try {
      const normalizedKeyword = String(keyword || '').trim()
      let items: any[] = []
      let statusCode = 200
      let pages = 1
      if (!normalizedKeyword) {
        const resp = await api.get(path, {
          params: {
            limit: 100,
            offset: 0,
          }
        })
        statusCode = Number(resp.status || 200)
        items = Array.isArray(resp.data?.items) ? resp.data.items : []
      } else {
        const pageSize = 500
        let offset = 0
        pages = 0
        while (true) {
          const resp = await api.get(path, {
            params: {
              limit: pageSize,
              offset,
              q: normalizedKeyword
            }
          })
          statusCode = Number(resp.status || 200)
          const part = Array.isArray(resp.data?.items) ? resp.data.items : []
          items.push(...part)
          pages += 1
          if (part.length < pageSize || pages >= 100) {
            break
          }
          offset += pageSize
        }
      }
      const options: StudentOption[] = items
        .map((item: any) => ({
          label: `${String(item?.student_id || '')} | ${String(item?.name || '-')}`,
          value: String(item?.student_id || '')
        }))
        .filter((item: StudentOption) => !!item.value)
      setStudentIdOptions(options)
      const tracePath = normalizedKeyword
        ? `${path}?mode=full_search&q=${encodeURIComponent(normalizedKeyword)}&pages=${pages}`
        : `${path}?limit=100&offset=0`
      pushTrace('GET', tracePath, statusCode, true, Math.round(performance.now() - start), { count: options.length })
    } catch (error: any) {
      const status = Number(error?.response?.status || 0)
      const tracePath = keyword
        ? `${path}?mode=full_search&q=${encodeURIComponent(keyword)}`
        : `${path}?limit=100&offset=0`
      pushTrace('GET', tracePath, status, false, Math.round(performance.now() - start), error?.response?.data || error?.message)
    }
  }

  useEffect(() => {
    loadGuide()
    loadJobs()
    loadStudents()
  }, [])

  const exportSkillLabels = async () => {
    const values = await skillExportForm.validateFields()
    const manualStudents = String(values.students || '')
      .split(',')
      .map((x: string) => x.trim())
      .filter(Boolean)
    const selectedStudents = Array.isArray(values.student_ids)
      ? values.student_ids.map((x: any) => String(x).trim()).filter(Boolean)
      : []
    const mergedStudents = Array.from(new Set([...manualStudents, ...selectedStudents]))
    const manualJobs = String(values.jobs || '')
      .split(',')
      .map((x: string) => x.trim())
      .filter(Boolean)
    const selectedJobs = Array.isArray(values.job_ids)
      ? values.job_ids.map((x: any) => String(x).trim()).filter(Boolean)
      : []
    const mergedJobs = Array.from(new Set([...manualJobs, ...selectedJobs]))

    setLoadingEval(true)
    const path = '/admin/eval/skill_match/export'
    const start = performance.now()
    try {
      const resp = await api.post(path, {
        students: mergedStudents.join(','),
        jobs: mergedJobs.join(',')
      })
      pushTrace('POST', path, Number(resp.status || 200), true, Math.round(performance.now() - start), resp.data)
      setSkillExportResult(resp.data || null)
      message.success(`技能标注底表导出成功，行数 ${resp.data?.row_count || 0}`)
    } catch (error: any) {
      const status = Number(error?.response?.status || 0)
      pushTrace('POST', path, status, false, Math.round(performance.now() - start), error?.response?.data || error?.message)
      message.error('技能标注底表导出失败')
    } finally {
      setLoadingEval(false)
    }
  }

  const exportProfileLabels = async () => {
    const values = await profileExportForm.validateFields()
    const manualStudents = String(values.students || '')
      .split(',')
      .map((x: string) => x.trim())
      .filter(Boolean)
    const selectedStudents = Array.isArray(values.student_ids)
      ? values.student_ids.map((x: any) => String(x).trim()).filter(Boolean)
      : []
    const mergedStudents = Array.from(new Set([...manualStudents, ...selectedStudents]))
    const manualJobs = String(values.jobs || '')
      .split(',')
      .map((x: string) => x.trim())
      .filter(Boolean)
    const selectedJobs = Array.isArray(values.job_ids)
      ? values.job_ids.map((x: any) => String(x).trim()).filter(Boolean)
      : []
    const mergedJobs = Array.from(new Set([...manualJobs, ...selectedJobs]))

    setLoadingEval(true)
    const path = '/admin/eval/profile/export'
    const start = performance.now()
    try {
      const resp = await api.post(path, {
        students: mergedStudents.join(','),
        jobs: mergedJobs.join(','),
        random_jobs: values.random_jobs,
        random_students: values.random_students,
        seed: values.seed
      })
      pushTrace('POST', path, Number(resp.status || 200), true, Math.round(performance.now() - start), resp.data)
      setProfileExportResult(resp.data || null)
      message.success(`画像标注底表导出成功，行数 ${resp.data?.row_count || 0}`)
    } catch (error: any) {
      const status = Number(error?.response?.status || 0)
      pushTrace('POST', path, status, false, Math.round(performance.now() - start), error?.response?.data || error?.message)
      message.error('画像标注底表导出失败')
    } finally {
      setLoadingEval(false)
    }
  }

  const runBatchPipeline = async () => {
    const values = await batchRunForm.validateFields()
    const manualStudents = String(values.students || '')
      .split(',')
      .map((x: string) => x.trim())
      .filter(Boolean)
    const selectedStudents = Array.isArray(values.student_ids)
      ? values.student_ids.map((x: any) => String(x).trim()).filter(Boolean)
      : []
    const studentIds = Array.from(new Set([...manualStudents, ...selectedStudents]))

    const manualJobs = String(values.jobs || '')
      .split(',')
      .map((x: string) => x.trim())
      .filter(Boolean)
    const selectedJobs = Array.isArray(values.job_ids)
      ? values.job_ids.map((x: any) => String(x).trim()).filter(Boolean)
      : []
    const jobIds = Array.from(new Set([...manualJobs, ...selectedJobs]))

    if (!studentIds.length) {
      message.warning('请至少选择一批学生ID')
      return
    }
    if (!jobIds.length) {
      message.warning('请至少选择一批岗位ID')
      return
    }

    setLoadingBatchRun(true)
    const path = '/admin/eval/batch_run'
    const start = performance.now()
    try {
      const resp = await api.post(path, {
        student_ids: studentIds,
        job_ids: jobIds,
        workers: values.workers,
        only_missing: values.only_missing,
        run_job_profiles: values.run_job_profiles,
        run_student_profiles: values.run_student_profiles,
        run_matches: values.run_matches,
        use_cache: values.use_cache,
        use_semantic_review: values.use_semantic_review
      })
      pushTrace('POST', path, Number(resp.status || 200), true, Math.round(performance.now() - start), resp.data)
      setBatchRunResult(resp.data || null)
      message.success(`批量执行完成：学生 ${resp.data?.student_count || 0}，岗位 ${resp.data?.job_count || 0}，配对 ${resp.data?.pair_count || 0}`)
    } catch (error: any) {
      const status = Number(error?.response?.status || 0)
      pushTrace('POST', path, status, false, Math.round(performance.now() - start), error?.response?.data || error?.message)
      message.error('批量执行失败')
    } finally {
      setLoadingBatchRun(false)
    }
  }

  const importSourcesAndGenerateProfiles = async () => {
    const values = await sourceImportForm.validateFields()
    if (!resumeFiles.length && !jobExcelFile) {
      message.warning('请先选择学生简历文件或岗位 Excel')
      return
    }
    setLoadingSourceImport(true)
    const nextResult: SourceImportResult = {}
    const collectedStudents: string[] = []
    const collectedJobs: string[] = []

    try {
      if (resumeFiles.length) {
        const path = '/admin/eval/import_student_resumes'
        const start = performance.now()
        const data = new FormData()
        resumeFiles.forEach((file) => data.append('files', file))
        data.append('student_id_prefix', String(values.student_id_prefix || 'STU'))
        data.append('overwrite_existing', String(Boolean(values.overwrite_existing)))
        data.append('require_llm', String(Boolean(values.require_llm)))
        data.append('workers', String(values.workers || 8))
        try {
          const resp = await api.post(path, data, { headers: { 'Content-Type': 'multipart/form-data' } })
          pushTrace('POST', path, Number(resp.status || 200), true, Math.round(performance.now() - start), resp.data)
          nextResult.students = resp.data
          collectedStudents.push(...(Array.isArray(resp.data?.student_ids) ? resp.data.student_ids : []))
        } catch (error: any) {
          const status = Number(error?.response?.status || 0)
          pushTrace('POST', path, status, false, Math.round(performance.now() - start), error?.response?.data || error?.message)
          throw error
        }
      }

      if (jobExcelFile) {
        const path = '/admin/eval/import_jobs_excel'
        const start = performance.now()
        const data = new FormData()
        data.append('file', jobExcelFile)
        data.append('sheet_name', String(values.sheet_name ?? 0))
        data.append('computer_only', String(Boolean(values.computer_only)))
        data.append('auto_generate_profiles', String(Boolean(values.auto_generate_profiles)))
        data.append('only_missing', String(Boolean(values.only_missing)))
        data.append('workers', String(values.workers || 12))
        try {
          const resp = await api.post(path, data, { headers: { 'Content-Type': 'multipart/form-data' } })
          pushTrace('POST', path, Number(resp.status || 200), true, Math.round(performance.now() - start), resp.data)
          nextResult.jobs = resp.data
          collectedJobs.push(...(Array.isArray(resp.data?.job_ids) ? resp.data.job_ids : []))
        } catch (error: any) {
          const status = Number(error?.response?.status || 0)
          pushTrace('POST', path, status, false, Math.round(performance.now() - start), error?.response?.data || error?.message)
          throw error
        }
      }

      setSourceImportResult(nextResult)
      batchRunForm.setFieldsValue({
        student_ids: collectedStudents,
        job_ids: collectedJobs,
        workers: values.workers || 12
      })
      skillExportForm.setFieldsValue({ student_ids: collectedStudents, job_ids: collectedJobs })
      profileExportForm.setFieldsValue({ student_ids: collectedStudents, job_ids: collectedJobs })
      message.success(`源数据处理完成：学生 ${collectedStudents.length}，岗位 ${collectedJobs.length}`)
      void loadJobs()
      void loadStudents()
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '源数据导入或画像生成失败')
    } finally {
      setLoadingSourceImport(false)
    }
  }

  const computeSkillAccuracy = async () => {
    if (!skillEvalFile) {
      message.warning('请先选择技能标注CSV')
      return
    }
    setLoadingEval(true)
    const path = '/admin/eval/skill_match/compute'
    const start = performance.now()
    try {
      const data = new FormData()
      data.append('file', skillEvalFile)
      const resp = await api.post(path, data, {
        headers: { 'Content-Type': 'multipart/form-data' }
      })
      pushTrace('POST', path, Number(resp.status || 200), true, Math.round(performance.now() - start), resp.data)
      setSkillEvalResult(resp.data || null)
      message.success(`技能准确率计算完成：${((resp.data?.accuracy || 0) * 100).toFixed(2)}%`)
    } catch (error: any) {
      const status = Number(error?.response?.status || 0)
      pushTrace('POST', path, status, false, Math.round(performance.now() - start), error?.response?.data || error?.message)
      message.error('技能准确率计算失败')
    } finally {
      setLoadingEval(false)
    }
  }

  const computeProfileAccuracy = async () => {
    if (!profileEvalFile) {
      message.warning('请先选择画像标注CSV')
      return
    }
    setLoadingEval(true)
    const path = '/admin/eval/profile/compute'
    const start = performance.now()
    try {
      const data = new FormData()
      data.append('file', profileEvalFile)
      const resp = await api.post(path, data, {
        headers: { 'Content-Type': 'multipart/form-data' }
      })
      pushTrace('POST', path, Number(resp.status || 200), true, Math.round(performance.now() - start), resp.data)
      setProfileEvalResult(resp.data || null)
      message.success(`画像准确率计算完成：${((resp.data?.accuracy || 0) * 100).toFixed(2)}%`)
    } catch (error: any) {
      const status = Number(error?.response?.status || 0)
      pushTrace('POST', path, status, false, Math.round(performance.now() - start), error?.response?.data || error?.message)
      message.error('画像准确率计算失败')
    } finally {
      setLoadingEval(false)
    }
  }

  return (
    <div className="page-stack">
      <Card className="section-card">
        <Space direction="vertical" size={6} style={{ width: '100%' }}>
          <Text className="page-kicker">独立验真页</Text>
          <Title level={3} style={{ margin: 0 }}>指标准确率验真台</Title>
        </Space>
      </Card>

      <Card className="section-card" title="三步完成验真（中文操作版）">
        <Paragraph style={{ marginBottom: 8 }}>1. 先选学生ID和岗位ID，点击“第1步：导出标注底表”。</Paragraph>
        <Paragraph style={{ marginBottom: 8 }}>2. 在导出的CSV里人工填写标注列：技能表填 <Text code>true_match</Text>，画像表填 <Text code>true_value</Text>。</Paragraph>
        <Paragraph style={{ marginBottom: 0 }}>3. 回到本页上传已标注CSV，点击“第3步：计算准确率”，看是否达到目标（技能≥80%，画像≥90%）。</Paragraph>
      </Card>

      <Card className="section-card" title="验收目标与接口" extra={<Button onClick={loadGuide} loading={loadingGuide}>刷新阈值</Button>}>
        <Paragraph type="secondary" style={{ marginBottom: 12 }}>
          下方接口地址仅用于“证明真实调用”，你不需要手动输入这些地址。
        </Paragraph>
        <Descriptions bordered size="small" column={2}>
          <Descriptions.Item label="技能匹配准确率目标">
            {`${(skillTarget * 100).toFixed(0)}%`}
          </Descriptions.Item>
          <Descriptions.Item label="画像准确率目标">
            {`${(profileTarget * 100).toFixed(0)}%`}
          </Descriptions.Item>
          <Descriptions.Item label="技能导出接口">{apiUrl('/admin/eval/skill_match/export')}</Descriptions.Item>
          <Descriptions.Item label="技能计算接口">{apiUrl('/admin/eval/skill_match/compute')}</Descriptions.Item>
          <Descriptions.Item label="画像导出接口">{apiUrl('/admin/eval/profile/export')}</Descriptions.Item>
          <Descriptions.Item label="画像计算接口">{apiUrl('/admin/eval/profile/compute')}</Descriptions.Item>
        </Descriptions>
      </Card>

      <Card className="section-card" title="源数据导入并生成画像">
        <Form
          form={sourceImportForm}
          layout="vertical"
          initialValues={{
            student_id_prefix: 'STU',
            sheet_name: 0,
            workers: 12,
            overwrite_existing: true,
            require_llm: false,
            computer_only: true,
            auto_generate_profiles: true,
            only_missing: true
          }}
        >
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item label="学生简历文件（支持批量 .docx/.pdf）">
                <Upload
                  multiple
                  beforeUpload={(_, fileList) => {
                    setResumeFiles(fileList as File[])
                    return false
                  }}
                  onRemove={(file) => {
                    setResumeFiles((prev) => prev.filter((item: any) => item.uid !== (file as any).uid))
                  }}
                  accept=".docx,.pdf"
                >
                  <Button icon={<UploadOutlined />}>选择一批学生简历</Button>
                </Upload>
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item label="岗位 Excel 表（.xls/.xlsx）">
                <Upload
                  beforeUpload={(file) => {
                    setJobExcelFile(file as File)
                    return false
                  }}
                  onRemove={() => {
                    setJobExcelFile(null)
                  }}
                  maxCount={1}
                  accept=".xls,.xlsx"
                >
                  <Button icon={<UploadOutlined />}>选择岗位 Excel</Button>
                </Upload>
              </Form.Item>
            </Col>
            <Col span={6}>
              <Form.Item label="学生ID前缀" name="student_id_prefix">
                <Input placeholder="STU" />
              </Form.Item>
            </Col>
            <Col span={6}>
              <Form.Item label="Excel工作表" name="sheet_name">
                <Input placeholder="默认 0" />
              </Form.Item>
            </Col>
            <Col span={6}>
              <Form.Item label="并发数" name="workers">
                <InputNumber min={1} max={32} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={24}>
              <Space wrap>
                <Form.Item name="overwrite_existing" valuePropName="checked" noStyle><Checkbox>覆盖已有学生画像</Checkbox></Form.Item>
                <Form.Item name="require_llm" valuePropName="checked" noStyle><Checkbox>学生画像强制要求大模型成功</Checkbox></Form.Item>
                <Form.Item name="computer_only" valuePropName="checked" noStyle><Checkbox>岗位表仅保留计算机相关岗位</Checkbox></Form.Item>
                <Form.Item name="auto_generate_profiles" valuePropName="checked" noStyle><Checkbox>导入岗位后生成岗位画像</Checkbox></Form.Item>
                <Form.Item name="only_missing" valuePropName="checked" noStyle><Checkbox>岗位画像只补缺失</Checkbox></Form.Item>
              </Space>
            </Col>
          </Row>
          <Button type="primary" loading={loadingSourceImport} onClick={importSourcesAndGenerateProfiles}>导入源数据并生成画像</Button>
        </Form>
        {sourceImportResult ? (
          <Descriptions bordered size="small" column={2} style={{ marginTop: 16 }}>
            <Descriptions.Item label="学生导入">{`上传 ${sourceImportResult.students?.uploaded || 0} / 画像成功 ${sourceImportResult.students?.profiles?.ok || 0} / 失败 ${sourceImportResult.students?.profiles?.failed || 0}`}</Descriptions.Item>
            <Descriptions.Item label="岗位导入">{`入库 ${sourceImportResult.jobs?.inserted || 0} / 画像成功 ${sourceImportResult.jobs?.profiles?.ok || 0} / 失败 ${sourceImportResult.jobs?.profiles?.failed || 0}`}</Descriptions.Item>
            <Descriptions.Item label="学生ID" span={2}>{(sourceImportResult.students?.student_ids || []).slice(0, 20).join(', ') || '-'}</Descriptions.Item>
            <Descriptions.Item label="岗位ID" span={2}>{(sourceImportResult.jobs?.job_ids || []).slice(0, 20).join(', ') || '-'}</Descriptions.Item>
          </Descriptions>
        ) : null}
      </Card>

      <Card className="section-card" title="批量预跑画像与匹配（高并发）">
        <Form
          form={batchRunForm}
          layout="vertical"
          initialValues={{
            students: '',
            student_ids: [],
            jobs: '',
            job_ids: [],
            workers: 12,
            only_missing: true,
            run_job_profiles: true,
            run_student_profiles: true,
            run_matches: true,
            use_cache: false,
            use_semantic_review: false
          }}
        >
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item label="学生ID（可空，逗号分隔）" name="students">
                <Input placeholder="如 S001,S002" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item label="学生ID快速选择" name="student_ids">
                <Select
                  mode="multiple"
                  allowClear
                  showSearch
                  optionFilterProp="label"
                  options={studentIdOptions}
                  placeholder="可按学生姓名搜索"
                />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item label="岗位ID（可空，逗号分隔）" name="jobs">
                <Input placeholder="如 JOB001,JOB002" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item label="岗位ID快速选择" name="job_ids">
                <Select
                  mode="multiple"
                  allowClear
                  showSearch
                  optionFilterProp="label"
                  options={jobIdOptions}
                  placeholder="可按岗位名称搜索"
                />
              </Form.Item>
            </Col>
            <Col span={6}>
              <Form.Item label="并发数" name="workers">
                <InputNumber min={1} max={32} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={18}>
              <Space wrap style={{ paddingTop: 30 }}>
                <Form.Item name="only_missing" valuePropName="checked" noStyle><Checkbox>只补缺失画像/结果</Checkbox></Form.Item>
                <Form.Item name="run_job_profiles" valuePropName="checked" noStyle><Checkbox>跑岗位画像</Checkbox></Form.Item>
                <Form.Item name="run_student_profiles" valuePropName="checked" noStyle><Checkbox>跑学生画像</Checkbox></Form.Item>
                <Form.Item name="run_matches" valuePropName="checked" noStyle><Checkbox>跑人岗匹配</Checkbox></Form.Item>
                <Form.Item name="use_cache" valuePropName="checked" noStyle><Checkbox>匹配用缓存</Checkbox></Form.Item>
                <Form.Item name="use_semantic_review" valuePropName="checked" noStyle><Checkbox>开启语义复核</Checkbox></Form.Item>
              </Space>
            </Col>
          </Row>
          <Space>
            <Button type="primary" loading={loadingBatchRun} onClick={runBatchPipeline}>开始高并发批量执行</Button>
          </Space>
        </Form>
        {batchRunResult ? (
          <Descriptions bordered size="small" column={2} style={{ marginTop: 16 }}>
            <Descriptions.Item label="开始时间">{String(batchRunResult.started_at || '-')}</Descriptions.Item>
            <Descriptions.Item label="结束时间">{String(batchRunResult.finished_at || '-')}</Descriptions.Item>
            <Descriptions.Item label="并发数">{String(batchRunResult.workers || '-')}</Descriptions.Item>
            <Descriptions.Item label="配对总数">{String(batchRunResult.pair_count || 0)}</Descriptions.Item>
            <Descriptions.Item label="岗位画像">{`成功 ${batchRunResult.job_profiles?.ok || 0} / 失败 ${batchRunResult.job_profiles?.failed || 0} / 跳过 ${batchRunResult.job_profiles?.skipped || 0}`}</Descriptions.Item>
            <Descriptions.Item label="学生画像">{`成功 ${batchRunResult.student_profiles?.ok || 0} / 失败 ${batchRunResult.student_profiles?.failed || 0} / 跳过 ${batchRunResult.student_profiles?.skipped || 0}`}</Descriptions.Item>
            <Descriptions.Item label="人岗匹配" span={2}>{`成功 ${batchRunResult.matches?.ok || 0} / 失败 ${batchRunResult.matches?.failed || 0} / 跳过 ${batchRunResult.matches?.skipped || 0}`}</Descriptions.Item>
          </Descriptions>
        ) : null}
      </Card>

      <Row gutter={[16, 16]}>
        <Col span={12}>
          <Card className="section-card" title="A. 技能匹配准确率（目标≥80%）">
            <Form form={skillExportForm} layout="vertical" initialValues={{ students: '', student_ids: [], jobs: '', job_ids: [] }}>
              <Form.Item label="学生ID（可空，逗号分隔）" name="students">
                <Input placeholder="如 S001,S002" />
              </Form.Item>
              <Form.Item label="学生ID快速选择（可按姓名搜索）" name="student_ids">
                <Select
                  mode="multiple"
                  allowClear
                  showSearch
                  options={studentIdOptions}
                  placeholder="可搜索姓名，例如 test赵、赵某某"
                  filterOption={false}
                  onSearch={(value) => { void loadStudents(String(value || '').trim()) }}
                />
              </Form.Item>
              <Form.Item label="岗位ID快速选择（可多选）" name="job_ids">
                <Select
                  mode="multiple"
                  allowClear
                  showSearch
                  options={jobIdOptions}
                  placeholder="从岗位台账直接选，避免遗漏岗位ID"
                  filterOption={false}
                  onSearch={(value) => { void loadJobs(String(value || '').trim()) }}
                />
              </Form.Item>
              <Form.Item label="岗位ID（可空，逗号分隔）" name="jobs">
                <Input placeholder="如 J001,J002" />
              </Form.Item>
              <Button type="primary" loading={loadingEval} onClick={exportSkillLabels}>第1步：导出技能标注底表</Button>
            </Form>

            {skillExportResult ? (
              <>
                {Number(skillExportResult?.row_count || 0) === 0 ? (
                  <Alert
                    style={{ marginTop: 12 }}
                    type="warning"
                    message="已导出成功，但当前是0行"
                    description="这通常表示该岗位目前还没有人岗匹配缓存记录（match_cache）。先去人岗匹配页跑一次该岗位评分，再回来导出。"
                  />
                ) : null}
                <Paragraph style={{ marginTop: 12, marginBottom: 0 }}>
                  导出路径：{String(skillExportResult.out_csv || '-')}
                </Paragraph>
                <Paragraph type="secondary" style={{ marginTop: 8, marginBottom: 8 }}>
                  下方样例表已展示 job_id 字段，导出的完整CSV也包含 job_id。
                </Paragraph>
                <Table
                  rowKey={(_, index) => String(index)}
                  columns={skillSampleColumns}
                  dataSource={skillSampleRows}
                  size="small"
                  scroll={{ x: 1100 }}
                  pagination={{ pageSize: 5 }}
                />
              </>
            ) : null}

            <div style={{ marginTop: 16 }}>
              <Upload beforeUpload={(file) => { setSkillEvalFile(file as File); return false }} maxCount={1} showUploadList>
                <Button icon={<UploadOutlined />}>第2步：选择已标注技能CSV文件</Button>
              </Upload>
              <Button style={{ marginTop: 12 }} type="primary" loading={loadingEval} onClick={computeSkillAccuracy}>第3步：计算技能准确率</Button>
            </div>

            {skillPass !== null ? (
              <Alert
                style={{ marginTop: 12 }}
                type={skillPass ? 'success' : 'error'}
                message={`技能准确率 ${(skillAccuracy * 100).toFixed(2)}%，${skillPass ? '达到' : '未达到'} ${(skillTarget * 100).toFixed(0)}%`}
              />
            ) : null}

            {skillEvalResult ? (
              <>
                <Descriptions bordered size="small" column={2} style={{ marginTop: 12 }}>
                  <Descriptions.Item label="准确率">{formatPercent(skillEvalResult?.accuracy)}</Descriptions.Item>
                  <Descriptions.Item label="精确率">{formatPercent(skillEvalResult?.precision)}</Descriptions.Item>
                  <Descriptions.Item label="召回率">{formatPercent(skillEvalResult?.recall)}</Descriptions.Item>
                  <Descriptions.Item label="F1">{formatPercent(skillEvalResult?.f1)}</Descriptions.Item>
                  <Descriptions.Item label="样本数">{String(skillEvalResult?.row_count ?? skillEvalResult?.total ?? '-')}</Descriptions.Item>
                  <Descriptions.Item label="是否达标">{skillPass ? '是' : '否'}</Descriptions.Item>
                </Descriptions>
                <details style={{ marginTop: 8 }}>
                  <summary>查看原始返回（技术字段）</summary>
                  <pre style={{ marginTop: 8, whiteSpace: 'pre-wrap' }}>{JSON.stringify(skillEvalResult, null, 2)}</pre>
                </details>
              </>
            ) : null}
          </Card>
        </Col>

        <Col span={12}>
          <Card className="section-card" title="B. 岗位/学生画像准确率（目标≥90%）">
            <Form
              form={profileExportForm}
              layout="vertical"
              initialValues={{ students: '', student_ids: [], jobs: '', job_ids: [], random_jobs: 50, random_students: 50, seed: 42 }}
            >
              <Form.Item label="学生ID快速选择（可按姓名搜索）" name="student_ids">
                <Select
                  mode="multiple"
                  allowClear
                  showSearch
                  options={studentIdOptions}
                  placeholder="可搜索姓名，例如 test赵、赵某某"
                  filterOption={false}
                  onSearch={(value) => { void loadStudents(String(value || '').trim()) }}
                />
              </Form.Item>
              <Form.Item label="学生ID（可空，逗号分隔）" name="students">
                <Input placeholder="如 S001,S002；为空表示不按学生ID过滤" />
              </Form.Item>
              <Form.Item label="岗位ID快速选择（可多选）" name="job_ids">
                <Select
                  mode="multiple"
                  allowClear
                  showSearch
                  options={jobIdOptions}
                  placeholder="从岗位台账直接选，避免遗漏岗位ID"
                  filterOption={false}
                  onSearch={(value) => { void loadJobs(String(value || '').trim()) }}
                />
              </Form.Item>
              <Form.Item label="岗位ID（可空，逗号分隔）" name="jobs">
                <Input placeholder="如 J001,J002；为空表示不按岗位ID过滤" />
              </Form.Item>
              <Row gutter={12}>
                <Col span={8}>
                  <Form.Item label="岗位抽样条数" name="random_jobs">
                    <InputNumber min={0} style={{ width: '100%' }} />
                  </Form.Item>
                </Col>
                <Col span={8}>
                  <Form.Item label="学生抽样条数" name="random_students">
                    <InputNumber min={0} style={{ width: '100%' }} />
                  </Form.Item>
                </Col>
                <Col span={8}>
                  <Form.Item label="随机种子（复现实验）" name="seed">
                    <InputNumber min={0} style={{ width: '100%' }} />
                  </Form.Item>
                </Col>
              </Row>
              <Button type="primary" loading={loadingEval} onClick={exportProfileLabels}>第1步：导出画像标注底表</Button>
            </Form>

            {profileExportResult ? (
              <>
                <Paragraph style={{ marginTop: 12, marginBottom: 0 }}>
                  导出路径：{String(profileExportResult.out_csv || '-')}
                </Paragraph>
                <Paragraph type="secondary" style={{ marginTop: 8, marginBottom: 8 }}>
                  画像导出中岗位ID与学生ID都在 entity_id 列：entity_type=job 时是岗位ID，entity_type=student 时是学生ID。
                </Paragraph>
                <Table
                  rowKey={(_, index) => String(index)}
                  columns={profileSampleColumns}
                  dataSource={profileSampleRows}
                  size="small"
                  scroll={{ x: 1100 }}
                  pagination={{ pageSize: 5 }}
                />
              </>
            ) : null}

            <div style={{ marginTop: 16 }}>
              <Upload beforeUpload={(file) => { setProfileEvalFile(file as File); return false }} maxCount={1} showUploadList>
                <Button icon={<UploadOutlined />}>第2步：选择已标注画像CSV文件</Button>
              </Upload>
              <Button style={{ marginTop: 12 }} type="primary" loading={loadingEval} onClick={computeProfileAccuracy}>第3步：计算画像准确率</Button>
            </div>

            {profilePass !== null ? (
              <Alert
                style={{ marginTop: 12 }}
                type={profilePass ? 'success' : 'error'}
                message={`画像准确率 ${(profileAccuracy * 100).toFixed(2)}%，${profilePass ? '达到' : '未达到'} ${(profileTarget * 100).toFixed(0)}%`}
              />
            ) : null}

            {profileEvalResult ? (
              <>
                <Descriptions bordered size="small" column={2} style={{ marginTop: 12 }}>
                  <Descriptions.Item label="准确率">{formatPercent(profileEvalResult?.accuracy)}</Descriptions.Item>
                  <Descriptions.Item label="精确率">{formatPercent(profileEvalResult?.precision)}</Descriptions.Item>
                  <Descriptions.Item label="召回率">{formatPercent(profileEvalResult?.recall)}</Descriptions.Item>
                  <Descriptions.Item label="F1">{formatPercent(profileEvalResult?.f1)}</Descriptions.Item>
                  <Descriptions.Item label="样本数">{String(profileEvalResult?.row_count ?? profileEvalResult?.total ?? '-')}</Descriptions.Item>
                  <Descriptions.Item label="是否达标">{profilePass ? '是' : '否'}</Descriptions.Item>
                </Descriptions>
                <details style={{ marginTop: 8 }}>
                  <summary>查看原始返回（技术字段）</summary>
                  <pre style={{ marginTop: 8, whiteSpace: 'pre-wrap' }}>{JSON.stringify(profileEvalResult, null, 2)}</pre>
                </details>
              </>
            ) : null}
          </Card>
        </Col>
      </Row>

      <Card className="section-card" title="调用轨迹（用于证明真实接口调用）">
        <Space style={{ marginBottom: 12 }}>
          <Badge status="processing" text={`累计 ${traces.length} 次调用`} />
          <Button onClick={() => setTraces([])}>清空轨迹</Button>
        </Space>
        <Table
          rowKey="id"
          columns={traceColumns}
          dataSource={traces}
          pagination={{ pageSize: 8 }}
          size="small"
          scroll={{ x: 980 }}
          expandable={{
            expandedRowRender: (row) => (
              <div>
                <div><Text strong>URL:</Text> {row.url}</div>
                <div><Text strong>响应摘要:</Text> {row.preview}</div>
              </div>
            )
          }}
        />
      </Card>
    </div>
  )
}
