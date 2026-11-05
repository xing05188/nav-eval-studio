<template>
  <div class="page">
    <div class="page-header">
      <div>
        <h2 class="page-title">用户管理</h2>
        <div class="page-subtitle">账号、角色与口令管理（仅管理员）</div>
      </div>
      <div class="header-actions">
        <el-button :icon="Refresh" :loading="loading" @click="loadUsers">刷新</el-button>
        <el-button type="primary" :icon="Plus" @click="openCreate">新增用户</el-button>
      </div>
    </div>

    <section class="panel">
      <div class="panel-header">
        <span class="panel-title">账号列表</span>
        <span class="sub">共 {{ rows.length }} 个账号</span>
      </div>
      <el-table v-loading="loading" :data="rows" empty-text="暂无用户">
        <el-table-column prop="id" label="#" width="56" />
        <el-table-column label="账号" min-width="180">
          <template #default="{ row }">
            <div class="user-cell">
              <div class="avatar" :class="row.role">{{ initials(row) }}</div>
              <div>
                <div class="user-name">
                  {{ row.display_name || row.username }}
                  <el-tag v-if="row.id === auth.user?.id" size="small" effect="plain" type="info">当前</el-tag>
                </div>
                <div class="sub mono">{{ row.username }}</div>
              </div>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="角色" width="120">
          <template #default="{ row }">
            <el-tag size="small" effect="light" :type="roleMeta(row.role).type">
              {{ roleMeta(row.role).label }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag size="small" :type="row.enabled ? 'success' : 'info'" effect="plain">
              {{ row.enabled ? '启用' : '已禁用' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="last_login_at" label="最近登录" width="168">
          <template #default="{ row }">
            <span class="mono tiny muted">{{ row.last_login_at || '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="创建时间" width="168">
          <template #default="{ row }">
            <span class="mono tiny muted">{{ row.created_at || '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="180" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
            <el-button link type="warning" @click="openReset(row)">重置口令</el-button>
          </template>
        </el-table-column>
      </el-table>
    </section>

    <el-dialog v-model="createVisible" title="新增用户" width="480px" :close-on-click-modal="false">
      <el-form ref="createRef" :model="createForm" :rules="createRules" label-width="86px">
        <el-form-item label="用户名" prop="username">
          <el-input v-model="createForm.username" placeholder="3-64 位字母、数字或 _.-" />
        </el-form-item>
        <el-form-item label="显示名">
          <el-input v-model="createForm.display_name" placeholder="例如 张三" maxlength="64" />
        </el-form-item>
        <el-form-item label="初始口令" prop="password">
          <el-input v-model="createForm.password" type="password" show-password placeholder="至少 6 位" />
        </el-form-item>
        <el-form-item label="角色">
          <el-select v-model="createForm.role" class="full">
            <el-option
              v-for="item in roleOptions"
              :key="item.value"
              :value="item.value"
              :label="item.label"
            />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submitCreate">创建</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="editVisible" :title="resetMode ? '重置口令' : '编辑用户'" width="480px" :close-on-click-modal="false">
      <el-form label-width="86px">
        <el-form-item label="用户名">
          <el-input :model-value="editForm.username" disabled />
        </el-form-item>
        <el-form-item label="显示名">
          <el-input v-model="editForm.display_name" maxlength="64" />
        </el-form-item>
        <el-form-item label="角色">
          <el-select v-model="editForm.role" class="full" :disabled="isSelf">
            <el-option
              v-for="item in roleOptions"
              :key="item.value"
              :value="item.value"
              :label="item.label"
            />
          </el-select>
          <span v-if="isSelf" class="hint">不能修改当前登录账号的角色</span>
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="editForm.enabled" :disabled="isSelf" />
          <span v-if="isSelf" class="hint">不能禁用当前登录账号</span>
        </el-form-item>
        <el-form-item :label="resetMode ? '新口令' : '重置口令'">
          <el-input
            v-model="editForm.password"
            type="password"
            show-password
            placeholder="留空表示不修改，至少 6 位"
          />
        </el-form-item>
        <el-alert
          v-if="resetMode"
          type="warning"
          :closable="false"
          show-icon
          title="保存后该账号需使用新口令重新登录"
        />
      </el-form>
      <template #footer>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submitEdit">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Plus, Refresh } from '@element-plus/icons-vue'
import { api } from '@/api'
import { useAuthStore } from '@/store/auth'

const auth = useAuthStore()
const rows = ref([])
const loading = ref(false)
const submitting = ref(false)
const createVisible = ref(false)
const editVisible = ref(false)
const resetMode = ref(false)
const createRef = ref(null)

const roleOptions = [
  { value: 'admin', label: '管理员' },
  { value: 'operator', label: '算法工程师' },
  { value: 'viewer', label: '访客' },
]

const createForm = reactive({
  username: '',
  display_name: '',
  password: '',
  role: 'operator',
})

const editForm = reactive({
  id: null,
  username: '',
  display_name: '',
  role: 'operator',
  enabled: true,
  password: '',
})

const createRules = {
  username: [
    { required: true, message: '请输入用户名', trigger: 'blur' },
    {
      pattern: /^[A-Za-z0-9_.-]{3,64}$/,
      message: '3-64 位字母、数字或 _.-',
      trigger: 'blur',
    },
  ],
  password: [
    { required: true, message: '请输入初始口令', trigger: 'blur' },
    { min: 6, message: '口令至少 6 位', trigger: 'blur' },
  ],
}

const isSelf = computed(() => editForm.id === auth.user?.id)

function roleMeta(role) {
  const map = {
    admin: { label: '管理员', type: 'danger' },
    operator: { label: '算法工程师', type: 'primary' },
    viewer: { label: '访客', type: 'info' },
  }
  return map[role] || { label: role || '未知', type: 'info' }
}

function initials(row) {
  const name = row.display_name || row.username || 'NA'
  return name.slice(0, 2).toUpperCase()
}

async function loadUsers() {
  loading.value = true
  try {
    rows.value = await api.users()
  } finally {
    loading.value = false
  }
}

function openCreate() {
  Object.assign(createForm, {
    username: '',
    display_name: '',
    password: '',
    role: 'operator',
  })
  createVisible.value = true
  createRef.value?.clearValidate()
}

function openEdit(row) {
  resetMode.value = false
  Object.assign(editForm, {
    id: row.id,
    username: row.username,
    display_name: row.display_name,
    role: row.role,
    enabled: row.enabled,
    password: '',
  })
  editVisible.value = true
}

function openReset(row) {
  openEdit(row)
  resetMode.value = true
}

async function submitCreate() {
  try {
    await createRef.value?.validate()
  } catch {
    return
  }
  submitting.value = true
  try {
    await api.createUser({ ...createForm })
    createVisible.value = false
    ElMessage.success('用户已创建')
    await loadUsers()
  } finally {
    submitting.value = false
  }
}

async function submitEdit() {
  if (editForm.password && editForm.password.length < 6) {
    ElMessage.warning('新口令至少 6 位')
    return
  }
  const payload = {
    display_name: editForm.display_name,
    role: editForm.role,
    enabled: editForm.enabled,
  }
  if (editForm.password) payload.password = editForm.password

  submitting.value = true
  try {
    await api.updateUser(editForm.id, payload)
    editVisible.value = false
    ElMessage.success('用户已更新')
    await loadUsers()
  } finally {
    submitting.value = false
  }
}

onMounted(loadUsers)
</script>

<style scoped>
.header-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.sub {
  color: var(--nav-text-muted);
  font-size: 12px;
  margin-top: 2px;
}

.user-cell {
  display: flex;
  align-items: center;
  gap: 10px;
}

.avatar {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  background: #eaf1ff;
  color: #2f6fed;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  font-weight: 600;
  flex: 0 0 32px;
}

.avatar.admin {
  background: #fdeaea;
  color: #dc2626;
}

.avatar.viewer {
  background: #eef2f7;
  color: #64748b;
}

.user-name {
  font-size: 13px;
  font-weight: 500;
  display: flex;
  align-items: center;
  gap: 6px;
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

.full {
  width: 100%;
}

.hint {
  width: 100%;
  font-size: 11px;
  color: #9aa8bc;
  margin-top: 2px;
}
</style>
