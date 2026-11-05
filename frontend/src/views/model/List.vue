<template>
  <div class="page">
    <div class="page-header">
      <div>
        <h2 class="page-title">模型档案</h2>
        <div class="page-subtitle">登记推理后端、权重路径与允许的输入类型，供评测任务引用</div>
      </div>
      <el-button type="primary" :icon="Plus" @click="openCreate">登记模型</el-button>
    </div>

    <section class="panel">
      <el-table v-loading="loading" :data="rows" empty-text="暂无模型档案">
        <el-table-column prop="id" label="#" width="56" />
        <el-table-column label="名称" min-width="200">
          <template #default="{ row }">
            <div class="name">{{ row.name }}</div>
            <div class="sub">{{ row.description }}</div>
          </template>
        </el-table-column>
        <el-table-column label="家族" width="110">
          <template #default="{ row }">
            <el-tag size="small" effect="plain" :type="row.family === 'mock' ? 'info' : 'primary'">
              {{ familyLabel(row.family) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="输入" min-width="160">
          <template #default="{ row }">
            <el-tag
              v-for="item in row.allowed_inputs"
              :key="item"
              size="small"
              effect="plain"
              class="input-tag"
            >
              {{ item }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag size="small" round :type="modelStatus(row.status).type">
              {{ modelStatus(row.status).label }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="权重路径" min-width="220" show-overflow-tooltip>
          <template #default="{ row }">
            <span class="mono sub">{{ row.weights_path || '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="190" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" :loading="probing === row.id" @click="probe(row)">
              探测
            </el-button>
            <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
            <el-button link type="danger" :disabled="!auth.isAdmin" @click="remove(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </section>

    <el-dialog
      v-model="dialogVisible"
      :title="editing ? '编辑模型档案' : '登记模型'"
      width="600px"
      :close-on-click-modal="false"
    >
      <el-form ref="formRef" :model="form" :rules="rules" label-width="96px">
        <el-form-item label="名称" prop="name">
          <el-input v-model="form.name" placeholder="例如 StreamVLN-R2R-RxR-v1.3" />
        </el-form-item>
        <el-form-item label="家族">
          <el-select v-model="form.family" style="width: 100%" :disabled="Boolean(editing)">
            <el-option label="StreamVLN（真实推理）" value="streamvln" />
            <el-option label="Mock（离线演示）" value="mock" />
            <el-option label="自定义" value="custom" />
          </el-select>
        </el-form-item>
        <el-form-item label="代码目录">
          <el-input v-model="form.code_path" placeholder="/path/to/StreamVLN" />
        </el-form-item>
        <el-form-item label="权重目录">
          <el-input v-model="form.weights_path" placeholder="/path/to/checkpoint" />
        </el-form-item>
        <el-form-item label="启动器">
          <el-input v-model="form.entry" placeholder="留空则使用 PATH 中的 torchrun" />
        </el-form-item>
        <el-form-item label="允许输入">
          <el-checkbox-group v-model="form.allowed_inputs">
            <el-checkbox label="rgb">RGB</el-checkbox>
            <el-checkbox label="depth">深度</el-checkbox>
            <el-checkbox label="pose">位姿</el-checkbox>
            <el-checkbox label="action">动作</el-checkbox>
          </el-checkbox-group>
        </el-form-item>
        <el-form-item label="需要 GPU">
          <el-switch v-model="form.needs_gpu" />
        </el-form-item>
        <el-form-item label="说明">
          <el-input v-model="form.description" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submit">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="probeVisible" title="可用性探测" width="520px">
      <div v-if="probeResult" class="probe">
        <el-tag :type="probeResult.status === 'available' ? 'success' : 'warning'" effect="dark">
          {{ probeResult.status === 'available' ? '配置完整' : '配置缺失' }}
        </el-tag>
        <div class="check-list">
          <div v-for="item in probeResult.checks" :key="item.name" class="check">
            <el-icon :class="item.ok ? 'ok' : 'bad'">
              <CircleCheck v-if="item.ok" />
              <CircleClose v-else />
            </el-icon>
            <div class="check-body">
              <div class="check-name">{{ item.name }}</div>
              <div class="check-detail mono">{{ item.detail || '—' }}</div>
            </div>
          </div>
        </div>
        <el-alert type="info" :closable="false" :title="probeResult.suggestion" show-icon />
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { CircleCheck, CircleClose, Plus } from '@element-plus/icons-vue'
import { api } from '@/api'
import { useAuthStore } from '@/store/auth'

const auth = useAuthStore()

const rows = ref([])
const loading = ref(false)
const saving = ref(false)
const probing = ref(null)
const dialogVisible = ref(false)
const probeVisible = ref(false)
const probeResult = ref(null)
const editing = ref(null)
const formRef = ref(null)

const form = reactive({
  name: '',
  family: 'streamvln',
  code_path: '',
  weights_path: '',
  entry: '',
  allowed_inputs: ['rgb', 'depth', 'pose', 'action'],
  needs_gpu: true,
  description: '',
})

const rules = {
  name: [{ required: true, message: '请输入名称', trigger: 'blur' }],
}

const familyLabel = (family) =>
  ({ streamvln: 'StreamVLN', mock: '离线演示', custom: '自定义' })[family] || family

const modelStatus = (status) =>
  ({
    available: { label: '可用', type: 'success' },
    missing: { label: '缺配置', type: 'danger' },
    disabled: { label: '已禁用', type: 'info' },
    unknown: { label: '未探测', type: 'info' },
  })[status] || { label: status, type: 'info' }

async function load() {
  loading.value = true
  try {
    rows.value = await api.models()
  } finally {
    loading.value = false
  }
}

function openCreate() {
  editing.value = null
  Object.assign(form, {
    name: '',
    family: 'streamvln',
    code_path: '',
    weights_path: '',
    entry: '',
    allowed_inputs: ['rgb', 'depth', 'pose', 'action'],
    needs_gpu: true,
    description: '',
  })
  dialogVisible.value = true
}

function openEdit(row) {
  editing.value = row
  Object.assign(form, {
    name: row.name,
    family: row.family,
    code_path: row.code_path,
    weights_path: row.weights_path,
    entry: row.entry,
    allowed_inputs: [...row.allowed_inputs],
    needs_gpu: row.needs_gpu,
    description: row.description,
  })
  dialogVisible.value = true
}

async function submit() {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return
  saving.value = true
  try {
    const payload = { ...form }
    if (editing.value) {
      delete payload.family
      await api.updateModel(editing.value.id, payload)
    } else {
      await api.createModel(payload)
    }
    ElMessage.success('已保存')
    dialogVisible.value = false
    await load()
  } finally {
    saving.value = false
  }
}

async function probe(row) {
  probing.value = row.id
  try {
    probeResult.value = await api.probeModel(row.id)
    probeVisible.value = true
    await load()
  } finally {
    probing.value = null
  }
}

async function remove(row) {
  const confirmed = await ElMessageBox.confirm(`确认删除模型「${row.name}」？`, '删除确认', {
    type: 'warning',
  }).catch(() => false)
  if (!confirmed) return
  await api.deleteModel(row.id)
  ElMessage.success('已删除')
  await load()
}

onMounted(load)
</script>

<style scoped>
.name {
  font-weight: 500;
}

.sub {
  font-size: 12px;
  color: var(--nav-text-muted);
  margin-top: 2px;
}

.input-tag {
  margin-right: 4px;
}

.probe {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.check-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.check {
  display: flex;
  gap: 8px;
  align-items: flex-start;
}

.check .ok {
  color: #16a34a;
  margin-top: 2px;
}

.check .bad {
  color: #dc2626;
  margin-top: 2px;
}

.check-name {
  font-size: 13px;
}

.check-detail {
  font-size: 11px;
  color: var(--nav-text-muted);
  word-break: break-all;
}
</style>
