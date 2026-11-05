<template>
  <div class="page">
    <div class="page-header">
      <div>
        <h2 class="page-title">评测任务</h2>
        <div class="page-subtitle">配置快照、队列执行与运行状态监控</div>
      </div>
      <div class="header-actions">
        <el-button :icon="FolderOpened" @click="openImport">导入历史产物</el-button>
        <el-button type="primary" :icon="Plus" @click="openCreate">新建评测</el-button>
      </div>
    </div>

    <section class="panel">
      <div class="panel-header filters">
        <el-select v-model="filters.status" placeholder="全部状态" clearable style="width: 130px" @change="load">
          <el-option v-for="item in statusOptions" :key="item.value" :label="item.label" :value="item.value" />
        </el-select>
        <el-input
          v-model="filters.q"
          placeholder="搜索任务名称"
          clearable
          style="width: 220px"
          :prefix-icon="Search"
          @keyup.enter="reload"
          @clear="reload"
        />
        <el-button :icon="Search" @click="reload">查询</el-button>
        <span class="total">共 {{ total }} 个任务</span>
      </div>

      <el-table
        v-loading="loading"
        :data="rows"
        empty-text="暂无评测任务"
        :default-sort="{ prop: 'queued_at', order: 'descending' }"
        @sort-change="onSortChange"
      >
        <el-table-column prop="id" label="#" width="56" />
        <el-table-column label="任务" min-width="220">
          <template #default="{ row }">
            <el-link type="primary" :underline="false" @click="openTask(row)">{{ row.name }}</el-link>
            <div class="sub">{{ row.note || '—' }}</div>
          </template>
        </el-table-column>
        <el-table-column
          prop="queued_at"
          label="创建时间"
          width="165"
          sortable="custom"
          :sort-orders="['descending', 'ascending']"
          show-overflow-tooltip
        >
          <template #default="{ row }">
            <span class="mono tiny">{{ row.queued_at || '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="数据集 / 切分" min-width="190" show-overflow-tooltip>
          <template #default="{ row }">
            <div>{{ row.dataset_name }}</div>
            <div class="sub">{{ row.split_name }}</div>
          </template>
        </el-table-column>
        <el-table-column label="模型" min-width="160" show-overflow-tooltip>
          <template #default="{ row }">
            <span class="sub">{{ row.model_name }}</span>
          </template>
        </el-table-column>
        <el-table-column label="进度" width="150">
          <template #default="{ row }">
            <el-progress
              :percentage="percent(row)"
              :stroke-width="5"
              :show-text="false"
              :color="progressColor(row.status)"
            />
            <span class="mono tiny">{{ row.progress_done }}/{{ row.progress_total }}</span>
          </template>
        </el-table-column>
        <el-table-column label="SR" width="82">
          <template #default="{ row }">
            <span class="mono">{{ formatPercent(row.metrics?.sr) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag size="small" round :type="taskStatus(row.status).type">
              {{ taskStatus(row.status).label }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="耗时" width="90">
          <template #default="{ row }">
            <span class="mono tiny">{{ row.duration_s ? `${row.duration_s}s` : '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="210" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openTask(row)">监控</el-button>
            <el-button
              v-if="row.status === 'running'"
              link
              type="warning"
              @click="control(row, 'pause')"
            >
              暂停
            </el-button>
            <el-button
              v-if="row.status === 'paused'"
              link
              type="success"
              @click="control(row, 'resume')"
            >
              恢复
            </el-button>
            <el-button
              v-if="['queued', 'running', 'paused'].includes(row.status)"
              link
              type="danger"
              @click="control(row, 'cancel')"
            >
              取消
            </el-button>
            <el-button
              v-if="['failed', 'canceled'].includes(row.status)"
              link
              type="warning"
              @click="control(row, 'retry')"
            >
              重跑失败
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <div class="pager">
        <el-pagination
          v-model:current-page="page"
          v-model:page-size="pageSize"
          :total="total"
          layout="prev, pager, next, total"
          @current-change="load"
        />
      </div>
    </section>

    <el-dialog v-model="dialogVisible" title="新建评测任务" width="640px" :close-on-click-modal="false">
      <el-form ref="formRef" :model="form" :rules="rules" label-width="100px">
        <el-form-item label="任务名称" prop="name">
          <el-input v-model="form.name" placeholder="例如 geo-state-spatial-smoke20" />
        </el-form-item>
        <el-form-item label="数据集" prop="dataset_id">
          <el-select v-model="form.dataset_id" style="width: 100%" @change="onDatasetChange">
            <el-option
              v-for="item in datasets"
              :key="item.id"
              :label="`${item.name}（${item.episode_count} 条）`"
              :value="item.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="切分" prop="split_id">
          <el-select v-model="form.split_id" style="width: 100%" placeholder="先选择数据集">
            <el-option
              v-for="item in splits"
              :key="item.id"
              :label="`${item.name}（${item.episode_count} 条）`"
              :value="item.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="模型" prop="model_profile_id">
          <el-select v-model="form.model_profile_id" style="width: 100%">
            <el-option
              v-for="item in models"
              :key="item.id"
              :label="`${item.name}（${item.family}）`"
              :value="item.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="配置模板">
          <el-select v-model="form.template_id" style="width: 100%" @change="onTemplateChange">
            <el-option
              v-for="item in templates"
              :key="item.id"
              :label="item.name"
              :value="item.id"
            />
          </el-select>
        </el-form-item>

        <el-form-item label="运行参数">
          <div class="param-grid">
            <div class="param">
              <span>随机种子</span>
              <el-input-number v-model="form.overrides.seed" :min="0" :max="99999" size="small" />
            </div>
            <div class="param">
              <span>最大步数</span>
              <el-input-number v-model="form.overrides.max_steps" :min="10" :max="5000" :step="10" size="small" />
            </div>
            <div class="param">
              <span>历史窗口</span>
              <el-input-number v-model="form.overrides.history_len" :min="1" :max="64" size="small" />
            </div>
            <div class="param">
              <span>裁剪比例</span>
              <el-input-number v-model="form.overrides.prune_ratio" :min="0" :max="0.9" :step="0.05" size="small" />
            </div>
            <div class="param">
              <span>模拟时延(s)</span>
              <el-input-number
                v-model="form.overrides.mock_delay"
                :min="0"
                :max="5"
                :step="0.02"
                size="small"
                :disabled="selectedModel?.family !== 'mock'"
              />
            </div>
          </div>
        </el-form-item>

        <el-form-item label="GPU">
          <el-input v-model="form.gpu_ids" placeholder="例如 0 或 0,1，留空使用默认" style="width: 200px" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="form.note" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>

      <el-alert
        type="info"
        :closable="false"
        show-icon
        title="提交时固化配置快照；后续修改模板不会影响已创建任务。"
      />

      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submit">创建并入队</el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="importVisible"
      title="导入历史评测产物"
      width="860px"
      :close-on-click-modal="false"
    >
      <el-alert
        type="info"
        :closable="false"
        show-icon
        title="扫描 <根目录>/results/<实验名>/streamvln/result.json，按 (scene_id, episode_id) 与已登记数据集对齐，生成只含实际跑过 episode 的切分与任务。"
      />

      <el-form label-width="92px" class="import-form">
        <el-form-item label="产物根目录">
          <el-input v-model="importForm.root_path" placeholder="/home/zjr/StreamVLN-kaggle-backup">
            <template #append>
              <el-button :loading="scanning" @click="scan">扫描</el-button>
            </template>
          </el-input>
        </el-form-item>
        <el-form-item label="导入选项">
          <el-checkbox v-model="importForm.force" @change="preview && scan()">
            覆盖已导入的实验（删除后按当前产物重建）
          </el-checkbox>
        </el-form-item>
      </el-form>

      <div v-if="preview" class="import-summary">
        <el-tag size="small">扫描 {{ preview.scanned }} 个实验</el-tag>
        <el-tag size="small" type="warning">待导入 {{ readyCount }}</el-tag>
        <el-tag size="small" type="info">已导入 {{ skippedCount }}</el-tag>
        <el-tag v-if="unmatchedCount" size="small" type="danger">未对齐 {{ unmatchedCount }}</el-tag>
        <span class="mono tiny source">{{ preview.results_dir }}</span>
      </div>

      <el-table v-if="preview" :data="preview.items" height="300" size="small">
        <el-table-column prop="experiment" label="实验" min-width="190" show-overflow-tooltip />
        <el-table-column prop="dataset" label="对齐数据集" min-width="150" show-overflow-tooltip />
        <el-table-column label="对齐 / 记录" width="120">
          <template #default="{ row }">
            <span class="mono tiny">{{ row.matched }} / {{ row.records }}</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="120">
          <template #default="{ row }">
            <el-tag size="small" :type="importStatus(row.status).type">
              {{ importStatus(row.status).label }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="任务" width="90">
          <template #default="{ row }">
            <el-link
              v-if="row.task_id"
              type="primary"
              :underline="false"
              @click="openTask({ id: row.task_id })"
            >
              #{{ row.task_id }}
            </el-link>
            <span v-else class="sub">—</span>
          </template>
        </el-table-column>
      </el-table>

      <template #footer>
        <el-button @click="importVisible = false">关闭</el-button>
        <el-button type="primary" :loading="importing" :disabled="!readyCount" @click="runImport">
          开始导入
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { FolderOpened, Plus, Search } from '@element-plus/icons-vue'
import { api } from '@/api'
import { formatPercent } from '@/utils/format'

const router = useRouter()

const rows = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const loading = ref(false)
const filters = reactive({ status: '', q: '', order: 'desc' })

const dialogVisible = ref(false)
const saving = ref(false)
const formRef = ref(null)

const importVisible = ref(false)
const scanning = ref(false)
const importing = ref(false)
const preview = ref(null)
const importForm = reactive({ root_path: '', force: false })

const readyCount = computed(
  () => preview.value?.items.filter((item) => item.status === 'ready').length || 0,
)
const skippedCount = computed(
  () =>
    preview.value?.items.filter((item) => ['skipped', 'imported'].includes(item.status)).length || 0,
)
const unmatchedCount = computed(
  () => preview.value?.items.filter((item) => item.status === 'unmatched').length || 0,
)

const datasets = ref([])
const splits = ref([])
const models = ref([])
const templates = ref([])

const form = reactive({
  name: '',
  dataset_id: null,
  split_id: null,
  model_profile_id: null,
  template_id: null,
  gpu_ids: '',
  note: '',
  overrides: { seed: 42, max_steps: 500, history_len: 8, prune_ratio: 0, mock_delay: 0.08 },
})

const rules = {
  name: [{ required: true, message: '请输入任务名称', trigger: 'blur' }],
  dataset_id: [{ required: true, message: '请选择数据集', trigger: 'change' }],
  split_id: [{ required: true, message: '请选择切分', trigger: 'change' }],
  model_profile_id: [{ required: true, message: '请选择模型', trigger: 'change' }],
}

const statusOptions = [
  { value: 'queued', label: '排队中' },
  { value: 'running', label: '运行中' },
  { value: 'paused', label: '已暂停' },
  { value: 'succeeded', label: '已完成' },
  { value: 'failed', label: '失败' },
  { value: 'canceled', label: '已取消' },
]

const selectedModel = computed(() => models.value.find((item) => item.id === form.model_profile_id))

function taskStatus(status) {
  const map = {
    queued: { label: '排队中', type: 'info' },
    preparing: { label: '准备中', type: 'warning' },
    running: { label: '运行中', type: 'primary' },
    paused: { label: '已暂停', type: 'warning' },
    succeeded: { label: '已完成', type: 'success' },
    failed: { label: '失败', type: 'danger' },
    canceled: { label: '已取消', type: 'info' },
  }
  return map[status] || { label: status, type: 'info' }
}

function percent(row) {
  if (!row.progress_total) return 0
  return Math.min(100, Math.round((row.progress_done / row.progress_total) * 100))
}

function progressColor(status) {
  if (status === 'failed') return '#dc2626'
  if (status === 'paused') return '#d97706'
  if (status === 'succeeded') return '#16a34a'
  return '#2f6fed'
}

async function load() {
  loading.value = true
  try {
    const data = await api.tasks({
      status: filters.status || undefined,
      q: filters.q || undefined,
      order: filters.order,
      page: page.value,
      page_size: pageSize.value,
    })
    rows.value = data.items
    total.value = data.total
  } finally {
    loading.value = false
  }
}

function reload() {
  page.value = 1
  load()
}

function onSortChange({ prop, order }) {
  if (prop !== 'queued_at') return
  const next = order === 'descending' ? 'desc' : 'asc'
  if (next === filters.order) return
  filters.order = next
  reload()
}

async function openCreate() {
  const [datasetList, modelList, templateList] = await Promise.all([
    api.datasets(),
    api.models(),
    api.templates(),
  ])
  datasets.value = datasetList
  models.value = modelList
  templates.value = templateList

  Object.assign(form, {
    name: '',
    dataset_id: datasetList[0]?.id || null,
    split_id: null,
    model_profile_id: modelList.find((m) => m.family === 'mock')?.id || modelList[0]?.id || null,
    template_id: templateList[0]?.id || null,
    gpu_ids: '',
    note: '',
    overrides: { seed: 42, max_steps: 500, history_len: 8, prune_ratio: 0, mock_delay: 0.08 },
  })
  if (form.dataset_id) await onDatasetChange(form.dataset_id)
  dialogVisible.value = true
}

async function onDatasetChange(datasetId) {
  if (!datasetId) return
  const detail = await api.datasetDetail(datasetId)
  splits.value = detail.splits || []
  form.split_id = splits.value[0]?.id || null
}

function onTemplateChange(templateId) {
  const template = templates.value.find((item) => item.id === templateId)
  if (!template) return
  form.overrides.history_len = template.params?.history_len ?? 8
  form.overrides.prune_ratio = template.params?.prune_ratio ?? 0
  if (!form.name) {
    form.name = `${template.name.replace(/[·+]/g, '-')}-${new Date().toISOString().slice(5, 10)}`
  }
}

async function submit() {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return
  saving.value = true
  try {
    const task = await api.createTask({
      name: form.name.trim(),
      dataset_id: form.dataset_id,
      split_id: form.split_id,
      model_profile_id: form.model_profile_id,
      template_id: form.template_id,
      gpu_ids: form.gpu_ids,
      note: form.note,
      overrides: { ...form.overrides },
    })
    dialogVisible.value = false
    ElMessage.success('任务已创建并进入队列')
    router.push(`/tasks/${task.id}`)
  } finally {
    saving.value = false
  }
}

async function control(row, action) {
  const names = { pause: '暂停', resume: '恢复', cancel: '取消', retry: '重跑失败项' }
  if (action === 'cancel' || action === 'retry') {
    const confirmed = await ElMessageBox.confirm(
      `确认${names[action]}任务「${row.name}」？`,
      '操作确认',
      { type: 'warning' },
    ).catch(() => false)
    if (!confirmed) return
  }
  try {
    const actionFn = {
      pause: api.pauseTask,
      resume: api.resumeTask,
      cancel: api.cancelTask,
      retry: api.retryTask,
    }[action]
    const result = await actionFn(row.id)
    ElMessage.success(`${names[action]}成功：${result.status}`)
    await load()
  } catch {
    // 错误已提示
  }
}

function openTask(row) {
  router.push(`/tasks/${row.id}`)
}

function importStatus(status) {
  const map = {
    ready: { label: '待导入', type: 'warning' },
    created: { label: '已新增', type: 'success' },
    updated: { label: '已同步更新', type: 'success' },
    imported: { label: '已导入', type: 'info' },
    skipped: { label: '已存在', type: 'info' },
    unmatched: { label: '未对齐', type: 'danger' },
    failed: { label: '失败', type: 'danger' },
  }
  return map[status] || { label: status, type: 'info' }
}

async function openImport() {
  importVisible.value = true
  preview.value = null
  importForm.force = false
  try {
    const sources = await api.importSources()
    importForm.root_path = sources.root || ''
    if (sources.experiments) {
      await scan()
    } else {
      ElMessage.warning(sources.message || '绑定目录下没有可用产物，请检查路径')
    }
  } catch {
    // 错误已提示
  }
}

async function scan() {
  if (!importForm.root_path.trim()) {
    ElMessage.warning('请填写产物根目录')
    return
  }
  scanning.value = true
  try {
    preview.value = await api.importResults({
      root_path: importForm.root_path.trim(),
      dry_run: true,
      force: importForm.force,
    })
  } catch {
    preview.value = null
  } finally {
    scanning.value = false
  }
}

async function runImport() {
  importing.value = true
  try {
    const result = await api.importResults({
      root_path: importForm.root_path.trim(),
      force: importForm.force,
    })
    preview.value = result
    const failed = result.failed || 0
    const text = `导入完成：新增 ${result.created}，覆盖 ${result.updated}，跳过 ${result.skipped}，失败 ${failed}`
    if (failed) {
      ElMessage.warning(text)
    } else {
      ElMessage.success(text)
    }
    page.value = 1
    await load()
  } catch {
    // 错误已提示
  } finally {
    importing.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.filters {
  gap: 10px;
  flex-wrap: wrap;
}

.header-actions {
  display: flex;
  gap: 10px;
}

.import-form {
  margin-top: 14px;
}

.import-summary {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 12px 0 10px;
  padding: 9px 12px;
  flex-wrap: wrap;
  background: #f8fafd;
  border: 1px solid var(--nav-border);
  border-radius: var(--nav-radius-sm);
}

.import-summary .source {
  color: var(--nav-text-muted);
  margin-left: auto;
}

.total {
  margin-left: auto;
  font-size: var(--nav-font-caption);
  color: var(--nav-text-muted);
  white-space: nowrap;
}

.sub {
  font-size: 12px;
  color: var(--nav-text-muted);
  margin-top: 2px;
}

.tiny {
  font-size: 11px;
}

.pager {
  display: flex;
  justify-content: flex-end;
  padding: 12px 16px;
  border-top: 1px solid var(--nav-border);
}

.param-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 10px 12px;
  width: 100%;
}

.param {
  display: flex;
  flex-direction: column;
  gap: 5px;
  font-size: 12px;
  color: var(--nav-text-muted);
  padding: 8px 10px;
  background: #f8fafd;
  border: 1px solid var(--nav-border);
  border-radius: var(--nav-radius-xs);
}
</style>
