<template>
  <div class="page">
    <div class="page-header">
      <div>
        <h2 class="page-title">操作审计</h2>
        <div class="page-subtitle">登录、任务、数据与配置变更记录（仅管理员）</div>
      </div>
      <el-button :icon="Refresh" :loading="loading" @click="loadAudit">刷新</el-button>
    </div>

    <section class="panel">
      <div class="panel-header filters">
        <el-input
          v-model="filters.action"
          placeholder="操作前缀，例如 task. / login"
          clearable
          class="filter-action"
          :prefix-icon="Search"
          @keyup.enter="reload"
          @clear="reload"
        />
        <el-select
          v-model="filters.target_type"
          placeholder="全部对象"
          clearable
          class="filter-target"
          @change="reload"
        >
          <el-option v-for="item in targetOptions" :key="item.value" :value="item.value" :label="item.label" />
        </el-select>
        <el-button :icon="Search" @click="reload">查询</el-button>
        <span class="total">共 {{ total }} 条记录</span>
      </div>

      <el-table v-loading="loading" :data="rows" empty-text="暂无审计记录">
        <el-table-column prop="id" label="#" width="66" />
        <el-table-column prop="created_at" label="时间" width="164">
          <template #default="{ row }">
            <span class="mono tiny muted">{{ row.created_at }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作者" width="120">
          <template #default="{ row }">
            <span>{{ row.username || '匿名' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" min-width="190">
          <template #default="{ row }">
            <el-tag size="small" effect="light" :type="actionMeta(row.action).type">
              {{ actionMeta(row.action).label }}
            </el-tag>
            <span class="action-code mono">{{ row.action }}</span>
          </template>
        </el-table-column>
        <el-table-column label="对象" width="150">
          <template #default="{ row }">
            <span class="mono tiny">{{ row.target_type || '—' }}</span>
            <span v-if="row.target_id" class="mono tiny muted"> #{{ row.target_id }}</span>
          </template>
        </el-table-column>
        <el-table-column label="详情" min-width="240" show-overflow-tooltip>
          <template #default="{ row }">
            <span class="detail-text">{{ detailText(row.detail) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="client_ip" label="来源 IP" width="132">
          <template #default="{ row }">
            <span class="mono tiny muted">{{ row.client_ip || '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="86" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openDetail(row)">详情</el-button>
          </template>
        </el-table-column>
      </el-table>

      <div class="pager">
        <el-pagination
          v-model:current-page="page"
          v-model:page-size="pageSize"
          :total="total"
          :page-sizes="[20, 50, 100]"
          layout="sizes, prev, pager, next, total"
          @current-change="loadAudit"
          @size-change="reload"
        />
      </div>
    </section>

    <el-drawer v-model="drawerVisible" title="审计详情" size="460px">
      <template v-if="activeRow">
        <el-descriptions :column="1" border size="small">
          <el-descriptions-item label="编号">{{ activeRow.id }}</el-descriptions-item>
          <el-descriptions-item label="时间">{{ activeRow.created_at }}</el-descriptions-item>
          <el-descriptions-item label="操作者">{{ activeRow.username || '匿名' }}</el-descriptions-item>
          <el-descriptions-item label="操作">
            {{ actionMeta(activeRow.action).label }}
            <span class="mono tiny muted">（{{ activeRow.action }}）</span>
          </el-descriptions-item>
          <el-descriptions-item label="对象">
            {{ activeRow.target_type || '—' }}
            <span v-if="activeRow.target_id"> #{{ activeRow.target_id }}</span>
          </el-descriptions-item>
          <el-descriptions-item label="来源 IP">{{ activeRow.client_ip || '—' }}</el-descriptions-item>
        </el-descriptions>
        <div class="drawer-title">详情</div>
        <pre class="detail-json">{{ prettyDetail }}</pre>
      </template>
    </el-drawer>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { Refresh, Search } from '@element-plus/icons-vue'
import { api } from '@/api'

const rows = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const loading = ref(false)
const drawerVisible = ref(false)
const activeRow = ref(null)

const filters = reactive({ action: '', target_type: '' })

const targetOptions = [
  { value: 'task', label: '评测任务' },
  { value: 'dataset', label: '数据集' },
  { value: 'split', label: '切分' },
  { value: 'model', label: '模型档案' },
  { value: 'template', label: '配置模板' },
  { value: 'setting', label: '系统设置' },
  { value: 'user', label: '用户' },
  { value: 'report', label: '报告' },
]

const ACTION_LABELS = {
  login: '登录',
  'login.failed': '登录失败',
  logout: '登出',
  'password.change': '修改口令',
  'task.create': '创建任务',
  'task.cancel': '取消任务',
  'task.pause': '暂停任务',
  'task.resume': '恢复任务',
  'task.retry': '重跑任务',
  'dataset.create': '登记数据集',
  'dataset.update': '更新数据集',
  'dataset.delete': '删除数据集',
  'dataset.scan': '扫描数据集',
  'dataset.export_causal': '导出因果切片',
  'split.create': '生成切分',
  'split.delete': '删除切分',
  'model.create': '登记模型',
  'model.update': '更新模型',
  'model.delete': '删除模型',
  'model.probe': '模型探测',
  'template.create': '新建模板',
  'template.update': '更新模板',
  'template.delete': '删除模板',
  'setting.update': '修改设置',
  'user.create': '新增用户',
  'user.update': '更新用户',
  'report.generate': '生成报告',
}

function actionMeta(action) {
  const label = ACTION_LABELS[action]
  if (action.includes('failed') || action.endsWith('.delete')) {
    return { label: label || action, type: 'danger' }
  }
  if (action.endsWith('.create')) return { label: label || action, type: 'success' }
  if (action.endsWith('.update') || action.endsWith('.pause') || action.endsWith('.cancel')) {
    return { label: label || action, type: 'warning' }
  }
  if (action.startsWith('login') || action === 'logout') {
    return { label: label || action, type: 'info' }
  }
  return { label: label || action, type: 'primary' }
}

function detailText(detail) {
  if (!detail || !Object.keys(detail).length) return '—'
  return Object.entries(detail)
    .map(([key, value]) => {
      const text = typeof value === 'object' ? JSON.stringify(value) : String(value)
      return `${key}=${text}`
    })
    .join(' · ')
}

const prettyDetail = computed(() =>
  activeRow.value ? JSON.stringify(activeRow.value.detail || {}, null, 2) : '{}',
)

async function loadAudit() {
  loading.value = true
  try {
    const data = await api.audit({
      page: page.value,
      page_size: pageSize.value,
      action: filters.action || undefined,
      target_type: filters.target_type || undefined,
    })
    rows.value = data.items || []
    total.value = data.total || 0
  } finally {
    loading.value = false
  }
}

function reload() {
  page.value = 1
  loadAudit()
}

function openDetail(row) {
  activeRow.value = row
  drawerVisible.value = true
}

onMounted(loadAudit)
</script>

<style scoped>
.filters {
  gap: 12px;
}

.filter-action {
  width: 250px;
}

.filter-target {
  width: 150px;
}

.total {
  margin-left: auto;
  font-size: 12px;
  color: var(--nav-text-muted);
}

.action-code {
  margin-left: 8px;
  font-size: 11px;
  color: #94a3b8;
}

.detail-text {
  font-size: 12px;
  color: #475569;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  display: block;
}

.mono {
  font-family: 'SFMono-Regular', Consolas, monospace;
}

.tiny {
  font-size: 11px;
}

.muted {
  color: var(--nav-text-muted);
}

.pager {
  display: flex;
  justify-content: flex-end;
  padding: 12px 18px;
}

.drawer-title {
  margin: 18px 0 8px;
  font-size: 13px;
  font-weight: 600;
}

.detail-json {
  background: #0f1b2f;
  color: #cbd8ea;
  border-radius: 8px;
  padding: 14px;
  font-size: 12px;
  line-height: 1.6;
  overflow: auto;
  max-height: 52vh;
  font-family: 'SFMono-Regular', Consolas, monospace;
}
</style>
