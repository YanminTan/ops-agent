import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
  timeout: 30000,
})

// SOP 管理
export const listSops = () => api.get('/sops')
export const getSop = (sopId) => api.get(`/sops/${sopId}`)
export const loadSop = (yamlContent) => api.post('/sops/load', yamlContent, {
  headers: { 'Content-Type': 'text/plain' }
})

// 诊断执行
export const startDiagnosis = (sopId, alertContext) => 
  api.post('/diagnosis/start', { sop_id: sopId, alert_context: alertContext })
export const getDiagnosis = (threadId) => api.get(`/diagnosis/${threadId}`)
export const approveInterrupt = (threadId, approved, comment = '') =>
  api.post(`/diagnosis/${threadId}/approve`, { approved, comment })

// 历史与回放
export const listThreads = () => api.get('/threads')
export const getThreadHistory = (threadId) => api.get(`/threads/${threadId}/history`)
export const replayToCheckpoint = (threadId, checkpointId) =>
  api.post(`/threads/${threadId}/replay`, { checkpoint_id: checkpointId })

// 工具
export const listTools = () => api.get('/tools')

// 健康检查
export const health = () => api.get('/health')

export default api
