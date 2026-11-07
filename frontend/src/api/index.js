import axios from 'axios'
import { ElMessage } from 'element-plus'

export const TOKEN_KEY = 'naveval_token'
export const USER_KEY = 'naveval_user'

const http = axios.create({
  baseURL: '/api',
  timeout: 30000,
})

http.interceptors.request.use((config) => {
  const token = localStorage.getItem(TOKEN_KEY)
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

http.interceptors.response.use(
  (response) => {
    const body = response.data
    if (body && typeof body === 'object' && 'code' in body) {
      if (body.code !== 0) {
        ElMessage.error(body.message || '请求失败')
        return Promise.reject(new Error(body.message))
      }
      return body.data
    }
    return body
  },
  (error) => {
    const status = error.response?.status
    const body = error.response?.data
    const message = body?.message || error.message || '网络异常'

    if (status === 401) {
      localStorage.removeItem(TOKEN_KEY)
      localStorage.removeItem(USER_KEY)
      if (!window.location.pathname.startsWith('/login')) {
        window.location.href = '/login'
      }
    } else {
      ElMessage.error(message)
    }
    return Promise.reject(new Error(message))
  },
)

export const api = {
  login: (payload) => http.post('/auth/login', payload),
  logout: () => http.post('/auth/logout'),
  me: () => http.get('/auth/me'),
  changePassword: (payload) => http.post('/auth/password', payload),

  overview: () => http.get('/overview'),
  systemStatus: () => http.get('/system/status'),
  gpus: () => http.get('/system/gpus'),
  settings: () => http.get('/settings'),
  updateSettings: (items) => http.put('/settings', { items }),

  users: () => http.get('/users'),
  createUser: (payload) => http.post('/users', payload),
  updateUser: (id, payload) => http.patch(`/users/${id}`, payload),
  audit: (params) => http.get('/audit', { params }),

  datasets: (params) => http.get('/datasets', { params }),
  createDataset: (payload) => http.post('/datasets', payload),
  datasetDetail: (id) => http.get(`/datasets/${id}`),
  updateDataset: (id, payload) => http.patch(`/datasets/${id}`, payload),
  deleteDataset: (id) => http.delete(`/datasets/${id}`),
  scanDataset: (id) => http.post(`/datasets/${id}/scan`),

  episodes: (id, params) => http.get(`/datasets/${id}/episodes`, { params }),
  episode: (id, rowId) => http.get(`/datasets/${id}/episodes/${rowId}`),
  observations: (id, rowId) => http.get(`/datasets/${id}/episodes/${rowId}/observations`),
  validateDataset: (id) => http.post(`/datasets/${id}/validate`),

  splits: (id) => http.get(`/datasets/${id}/splits`),
  createSplit: (id, payload) => http.post(`/datasets/${id}/splits`, payload),
  deleteSplit: (splitId) => http.delete(`/splits/${splitId}`),
  exportCausal: (id, payload) => http.post(`/datasets/${id}/export-causal`, payload),
  downloadExport: (id, filename) =>
    http.get(`/datasets/${id}/exports/${filename}`, { responseType: 'blob' }),

  models: () => http.get('/models'),
  createModel: (payload) => http.post('/models', payload),
  updateModel: (id, payload) => http.patch(`/models/${id}`, payload),
  deleteModel: (id) => http.delete(`/models/${id}`),
  probeModel: (id) => http.post(`/models/${id}/probe`),

  templates: () => http.get('/templates'),
  createTemplate: (payload) => http.post('/templates', payload),
  updateTemplate: (id, payload) => http.patch(`/templates/${id}`, payload),
  deleteTemplate: (id) => http.delete(`/templates/${id}`),

  tasks: (params) => http.get('/tasks', { params }),
  createTask: (payload) => http.post('/tasks', payload),
  taskDetail: (id) => http.get(`/tasks/${id}`),
  taskEpisodes: (id, params) => http.get(`/tasks/${id}/episodes`, { params }),
  taskLogs: (id, params) => http.get(`/tasks/${id}/logs`, { params }),
  taskSamples: (id, params) => http.get(`/tasks/${id}/samples`, { params }),
  cancelTask: (id) => http.post(`/tasks/${id}/cancel`),
  pauseTask: (id) => http.post(`/tasks/${id}/pause`),
  resumeTask: (id) => http.post(`/tasks/${id}/resume`),
  retryTask: (id) => http.post(`/tasks/${id}/retry-failed`),

  importSources: () => http.get('/import/sources'),
  importResults: (payload) => http.post('/import/results', payload, { timeout: 0 }),

  backupOverview: (params) => http.get('/import/backup', { params }),
  backupImport: (payload) => http.post('/import/backup', payload, { timeout: 0 }),
  updateBackupAuto: (payload) => http.put('/import/backup/auto', payload),
  backupAssets: (params) => http.get('/import/backup/assets', { params }),

  analysisTasks: (params) => http.get('/analysis/tasks', { params }),
  analysisCompare: (params) => http.get('/analysis/compare', { params }),
  analysisAblation: (params) => http.get('/analysis/ablation', { params }),
  analysisBootstrap: (payload) => http.post('/analysis/bootstrap', payload),
  analysisLongHorizon: (params) => http.get('/analysis/longhorizon', { params }),
  analysisFailures: (params) => http.get('/analysis/failures', { params }),

  replayEpisode: (taskId, rowId) => http.get(`/replay/${taskId}/${rowId}`),

  // 交互式仿真：画面走 <img src="/api/sim/stream?token=">，这里只封装 JSON 接口
  simStart: (payload) => http.post('/sim/sessions', payload, { timeout: 0 }),
  simState: () => http.get('/sim/state'),
  simAct: (action) => http.post('/sim/actions', { action }),
  simStop: (sessionId) => http.delete(`/sim/sessions/${sessionId || 'current'}`),
  // 模型驾驶：启用后权重在后台线程加载（约 12 s），这里不等加载完成
  simPolicyStart: (payload = {}) => http.post('/sim/policy', payload),
  simPolicyStop: () => http.delete('/sim/policy'),
  simPolicyPause: (paused) => http.post('/sim/policy/pause', { paused }),

  reports: (params) => http.get('/reports', { params }),
  createReport: (payload) => http.post('/reports', payload),
  downloadReport: (id) => http.get(`/reports/${id}/download`, { responseType: 'blob' }),
}

export function apiErrorMessage(error) {
  return error?.response?.data?.message || error?.message || '请求失败'
}


export default http
