<template>
  <div class="layout">
    <aside class="sidebar">
      <div class="brand">
        <img class="brand-mark" src="/favicon.png" alt="NavEval Studio" />
        <div class="brand-text">
          <div class="brand-name">NavEval Studio</div>
          <div class="brand-sub">具身导航评测与诊断</div>
        </div>
      </div>

      <el-menu
        :default-active="activeMenu"
        class="menu"
        background-color="transparent"
        text-color="#9fb0c9"
        active-text-color="#ffffff"
        router
      >
        <el-menu-item index="/overview">
          <el-icon><Odometer /></el-icon>
          <span>总览</span>
        </el-menu-item>

        <div class="menu-group">评测资产</div>
        <el-menu-item index="/datasets">
          <el-icon><FolderOpened /></el-icon>
          <span>数据集</span>
        </el-menu-item>
        <el-menu-item index="/models">
          <el-icon><Cpu /></el-icon>
          <span>模型档案</span>
        </el-menu-item>

        <div class="menu-group">评测执行</div>
        <el-menu-item index="/tasks">
          <el-icon><VideoPlay /></el-icon>
          <span>评测任务</span>
        </el-menu-item>
        <el-menu-item index="/replay">
          <el-icon><Position /></el-icon>
          <span>轨迹回放</span>
        </el-menu-item>

        <div class="menu-group">结果</div>
        <el-menu-item index="/analysis">
          <el-icon><DataAnalysis /></el-icon>
          <span>结果分析</span>
        </el-menu-item>
        <el-menu-item index="/reports">
          <el-icon><Document /></el-icon>
          <span>报告中心</span>
        </el-menu-item>

        <div class="menu-group">系统</div>
        <el-menu-item index="/backup-import">
          <el-icon><Download /></el-icon>
          <span>备份库导入</span>
        </el-menu-item>
        <el-menu-item index="/settings">
          <el-icon><Setting /></el-icon>
          <span>系统设置</span>
        </el-menu-item>
        <el-menu-item v-if="auth.isAdmin" index="/users">
          <el-icon><User /></el-icon>
          <span>用户管理</span>
        </el-menu-item>
        <el-menu-item v-if="auth.isAdmin" index="/audit">
          <el-icon><DocumentCopy /></el-icon>
          <span>操作审计</span>
        </el-menu-item>
      </el-menu>

      <div class="sidebar-footer">
        <span class="dot" />
        <span>V1.0.0 · 单机部署</span>
      </div>
    </aside>

    <div class="main">
      <header class="topbar">
        <div class="crumb">
          <span class="crumb-root">具身导航多模态流式评测与诊断软件</span>
          <el-icon class="crumb-sep"><ArrowRight /></el-icon>
          <span>{{ route.meta.title || '总览' }}</span>
        </div>

        <div class="topbar-right">
          <el-tag size="small" type="success" effect="plain" round>服务在线</el-tag>
          <el-dropdown trigger="click" @command="handleCommand">
            <div class="user">
              <div class="avatar">{{ initials }}</div>
              <div class="user-meta">
                <div class="user-name">{{ auth.displayName }}</div>
                <div class="user-role">{{ roleLabel }}</div>
              </div>
              <el-icon><ArrowDown /></el-icon>
            </div>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="profile" disabled>账号信息</el-dropdown-item>
                <el-dropdown-item command="logout" divided>退出登录</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </header>

      <main class="content">
        <router-view />
      </main>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/store/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const activeMenu = computed(() => route.path)
const initials = computed(() => (auth.displayName || 'NA').slice(0, 2).toUpperCase())
const roleLabel = computed(
  () => ({ admin: '管理员', operator: '算法工程师', viewer: '访客' })[auth.role] || '访客',
)

async function handleCommand(command) {
  if (command === 'logout') {
    await auth.logout()
    router.push('/login')
  }
}
</script>

<style scoped>
.layout {
  display: flex;
  min-height: 100vh;
}

.sidebar {
  width: 232px;
  flex: 0 0 232px;
  background: var(--nav-sidebar);
  display: flex;
  flex-direction: column;
  position: sticky;
  top: 0;
  height: 100vh;
  z-index: 12;
  border-right: 1px solid #1d2f4c;
}

.brand {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 18px;
  border-bottom: 1px solid #22344f;
}

.brand-mark {
  width: 34px;
  height: 34px;
  border-radius: var(--nav-radius-sm);
  display: block;
  object-fit: contain;
  flex: 0 0 34px;
}

.brand-name {
  color: #f3f6fb;
  font-size: 14px;
  font-weight: 600;
  line-height: 1.2;
}

.brand-sub {
  color: #7088a8;
  font-size: 11px;
  margin-top: 3px;
}

.menu {
  flex: 1;
  border-right: none;
  padding: 4px 10px;
  overflow-y: auto;
}

.menu :deep(.el-menu-item) {
  height: 38px;
  line-height: 38px;
  border-radius: var(--nav-radius-xs);
  margin-bottom: 2px;
  padding-left: 12px !important;
  font-size: 13px;
  font-weight: 500;
  transition: background-color var(--nav-duration) var(--nav-ease),
    color var(--nav-duration) var(--nav-ease);
}

.menu :deep(.el-menu-item:hover) {
  background: var(--nav-sidebar-hover);
}

.menu :deep(.el-menu-item.is-active) {
  background: var(--nav-accent);
  color: #fff;
  box-shadow: inset 3px 0 0 #a9c7ff;
}

.menu :deep(.el-menu-item.is-active .el-icon) {
  color: #fff;
}

.menu :deep(.el-menu-item.is-disabled) {
  opacity: 0.55;
}

.menu-group {
  display: flex;
  align-items: center;
  gap: 10px;
  color: #8296b2;
  font-size: 11px;
  letter-spacing: 0.8px;
  padding: 15px 12px 6px;
}

.menu-group::after {
  content: '';
  flex: 1;
  height: 1px;
  background: #233554;
}

.menu-tag {
  margin-left: auto;
  font-size: 10px;
  color: #6f86a6;
  border: 1px solid #2b3d59;
  border-radius: 4px;
  padding: 0 4px;
  line-height: 15px;
}

.sidebar-footer {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 13px 18px;
  color: #93a7c2;
  font-size: 11px;
  border-top: 1px solid #22344f;
}

.dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #3fbf6f;
  flex: 0 0 6px;
}

.main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}

.topbar {
  height: var(--nav-header-height);
  background: var(--nav-panel);
  border-bottom: 1px solid var(--nav-border);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
  position: sticky;
  top: 0;
  z-index: 10;
}

.crumb {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: var(--nav-text);
}

.crumb-root {
  color: var(--nav-text-subtle);
}

.crumb-sep {
  color: #c9d4e4;
  font-size: 11px;
}

.topbar-right {
  display: flex;
  align-items: center;
  gap: 16px;
}

.user {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  padding: 4px 8px;
  border-radius: 10px;
  transition: background-color var(--nav-duration) var(--nav-ease);
}

.user:hover {
  background: #f3f7fd;
}

.avatar {
  width: 30px;
  height: 30px;
  border-radius: 50%;
  background: var(--nav-accent-soft);
  color: var(--nav-accent-deep);
  font-size: 11px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 1px solid #cddefb;
}

.user-meta {
  line-height: 1.2;
}

.user-name {
  font-size: 13px;
  font-weight: 500;
}

.user-role {
  font-size: 11px;
  color: var(--nav-text-muted);
  margin-top: 2px;
}

.content {
  flex: 1;
  overflow-y: auto;
}

/* 小屏：侧边栏收为图标导航，与全局 768px 断点一致 */
@media (max-width: 768px) {
  .sidebar {
    width: 64px;
    flex-basis: 64px;
  }

  .brand {
    justify-content: center;
    padding: 14px 0;
  }

  .brand-text,
  .menu-group,
  .sidebar-footer > span:not(.dot) {
    display: none;
  }

  .menu {
    padding: 8px;
  }

  .menu :deep(.el-menu-item) {
    justify-content: center;
    padding: 0 !important;
  }

  .menu :deep(.el-menu-item span) {
    display: none;
  }

  .sidebar-footer {
    justify-content: center;
    padding: 13px 0;
  }

  .topbar {
    padding: 0 14px;
  }

  .crumb-root,
  .crumb-sep {
    display: none;
  }

  .topbar-right :deep(.el-tag) {
    display: none;
  }
}
</style>
