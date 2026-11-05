<template>
  <div class="page">
    <div class="page-header">
      <div>
        <h2 class="page-title">数据集</h2>
        <div class="page-subtitle">登记本地 R2R-CE / RxR-CE 数据，扫描 episode 并生成评测切分</div>
      </div>
      <el-button type="primary" :icon="Plus" @click="openCreate">登记数据集</el-button>
    </div>

    <section class="panel">
      <div class="panel-header filters">
        <div class="filter-left">
          <el-select v-model="filters.kind" placeholder="全部类型" clearable style="width: 140px" @change="load">
            <el-option label="R2R-CE" value="r2r_ce" />
            <el-option label="RxR-CE" value="rxr_ce" />
            <el-option label="自定义" value="custom" />
          </el-select>
          <el-select v-model="filters.status" placeholder="全部状态" clearable style="width: 130px" @change="load">
            <el-option label="可用" value="ready" />
            <el-option label="未扫描" value="unknown" />
            <el-option label="路径缺失" value="missing" />
            <el-option label="格式异常" value="invalid" />
          </el-select>
          <el-input
            v-model="filters.q"
            placeholder="搜索名称或路径"
            clearable
            style="width: 240px"
            :prefix-icon="Search"
            @keyup.enter="load"
            @clear="load"
          />
          <el-button :icon="Search" @click="load">查询</el-button>
        </div>
        <span class="count">共 {{ rows.length }} 个数据集</span>
      </div>

      <el-table
        v-loading="loading"
        :data="rows"
        empty-text="还没有数据集，点击右上角登记"
        :header-cell-style="{ fontSize: '12px' }"
      >
        <el-table-column prop="id" label="#" width="60" />
        <el-table-column label="名称" min-width="220">
          <template #default="{ row }">
            <div class="name">{{ row.name }}</div>
            <div class="sub mono">{{ row.version || '未标注版本' }}</div>
          </template>
        </el-table-column>
        <el-table-column label="类型" width="100">
          <template #default="{ row }">
            <el-tag size="small" effect="plain">{{ kindLabel(row.kind) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="104">
          <template #default="{ row }">
            <el-tag size="small" round :type="datasetStatus(row.status).type">
              {{ datasetStatus(row.status).label }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="Episode" width="110">
          <template #default="{ row }">
            <span class="mono">{{ row.episode_count }}</span>
          </template>
        </el-table-column>
        <el-table-column label="场景" width="90">
          <template #default="{ row }">
            <span class="mono">{{ row.scene_count }}</span>
          </template>
        </el-table-column>
        <el-table-column label="本地路径" min-width="240" show-overflow-tooltip>
          <template #default="{ row }">
            <span class="mono sub">{{ row.root_path }}</span>
          </template>
        </el-table-column>
        <el-table-column label="最近扫描" width="164">
          <template #default="{ row }">
            <span class="mono sub">{{ row.last_scan_at || '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="206" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openDetail(row)">详情</el-button>
            <el-button link type="primary" :loading="scanning === row.id" @click="scan(row)">
              扫描
            </el-button>
            <el-button link type="danger" :disabled="!auth.isAdmin" @click="remove(row)">
              删除
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </section>

    <el-dialog v-model="dialogVisible" title="登记数据集" width="560px" :close-on-click-modal="false">
      <el-form ref="formRef" :model="form" :rules="rules" label-width="92px" label-position="left">
        <el-form-item label="名称" prop="name">
          <el-input v-model="form.name" placeholder="例如 R2R-CE val_unseen" />
        </el-form-item>
        <el-form-item label="版本">
          <el-input v-model="form.version" placeholder="例如 v1-3" />
        </el-form-item>
        <el-form-item label="类型" prop="kind">
          <el-select v-model="form.kind" style="width: 100%">
            <el-option label="R2R-CE（Habitat episode 列表）" value="r2r_ce" />
            <el-option label="RxR-CE（guide + follower_gt）" value="rxr_ce" />
            <el-option label="自定义（JSON / JSONL）" value="custom" />
          </el-select>
        </el-form-item>
        <el-form-item label="数据路径" prop="root_path">
          <el-input v-model="form.root_path" placeholder="目录或单个 .json/.jsonl/.json.gz 文件" />
        </el-form-item>
        <el-form-item label="场景根目录">
          <el-input v-model="form.scene_root" placeholder="可选，用于校验 HM3D / MP3D 资产是否存在" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="form.note" type="textarea" :rows="2" placeholder="可选" />
        </el-form-item>
      </el-form>
      <div class="dialog-tip">
        登记只记录路径，不复制数据。保存后可点击「扫描」解析 episode 清单。
      </div>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submit">保存并扫描</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Search } from '@element-plus/icons-vue'
import { api } from '@/api'
import { useAuthStore } from '@/store/auth'
import { datasetStatus, kindLabel } from '@/utils/format'

const router = useRouter()
const auth = useAuthStore()

const rows = ref([])
const loading = ref(false)
const scanning = ref(null)
const saving = ref(false)
const dialogVisible = ref(false)
const formRef = ref(null)

const filters = reactive({ kind: '', status: '', q: '' })

const form = reactive({
  name: '',
  version: '',
  kind: 'r2r_ce',
  root_path: '',
  scene_root: '',
  note: '',
})

const rules = {
  name: [{ required: true, message: '请输入名称', trigger: 'blur' }],
  kind: [{ required: true, message: '请选择类型', trigger: 'change' }],
  root_path: [{ required: true, message: '请输入数据路径', trigger: 'blur' }],
}

async function load() {
  loading.value = true
  try {
    rows.value = await api.datasets({
      kind: filters.kind || undefined,
      status: filters.status || undefined,
      q: filters.q || undefined,
    })
  } finally {
    loading.value = false
  }
}

function openCreate() {
  Object.assign(form, {
    name: '',
    version: '',
    kind: 'r2r_ce',
    root_path: '',
    scene_root: '',
    note: '',
  })
  dialogVisible.value = true
}

async function submit() {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return
  saving.value = true
  try {
    const created = await api.createDataset({ ...form })
    dialogVisible.value = false
    ElMessage.success('已登记，开始扫描')
    await scan(created)
    await load()
  } finally {
    saving.value = false
  }
}

async function scan(row) {
  scanning.value = row.id
  try {
    const result = await api.scanDataset(row.id)
    ElMessage.success(`扫描完成：${result.episode_count} 条 episode，${result.scene_count} 个场景`)
    await load()
  } finally {
    scanning.value = null
  }
}

function openDetail(row) {
  router.push(`/datasets/${row.id}`)
}

async function remove(row) {
  const confirmed = await ElMessageBox.confirm(
    `确认删除数据集「${row.name}」？其 episode 索引将一并删除。`,
    '删除确认',
    { type: 'warning' },
  ).catch(() => false)
  if (!confirmed) return
  try {
    await api.deleteDataset(row.id)
    ElMessage.success('已删除')
    await load()
  } catch {
    // 错误已由拦截器提示
  }
}

onMounted(load)
</script>

<style scoped>
.filters {
  gap: 12px;
}

.filter-left {
  display: flex;
  gap: 10px;
  align-items: center;
}

.count {
  font-size: 12px;
  color: var(--nav-text-muted);
}

.name {
  font-weight: 500;
}

.sub {
  font-size: 12px;
  color: var(--nav-text-muted);
}

.dialog-tip {
  font-size: 12px;
  color: var(--nav-text-muted);
  background: #f8fafc;
  border-radius: 8px;
  padding: 8px 10px;
}
</style>
