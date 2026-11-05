<template>
  <div class="login-page">
    <section class="brand-side">
      <div class="brand-top">
        <img class="brand-mark" src="/favicon.png" alt="NavEval Studio" />
        <span class="brand-name">NavEval Studio</span>
      </div>

      <div class="brand-body">
        <div class="eyebrow">用于 R2R-CE 与 RxR-CE 基准的评测、诊断与回放</div>
        <h1>具身导航多模态流式<br />评测与诊断软件</h1>
        <p class="lede">
          面向连续环境视觉语言导航模型，覆盖数据准备、任务调度、轨迹回放与指标诊断的完整评测闭环。
        </p>

        <div class="features">
          <div class="feature">
            <div class="feature-icon"><el-icon><FolderOpened /></el-icon></div>
            <div>
              <div class="feature-title">数据与切分</div>
              <div class="feature-desc">多源观测对齐、质量校验、严格因果切片</div>
            </div>
          </div>
          <div class="feature">
            <div class="feature-icon"><el-icon><VideoPlay /></el-icon></div>
            <div>
              <div class="feature-title">评测调度</div>
              <div class="feature-desc">配置快照、队列执行、断点续跑与资源采样</div>
            </div>
          </div>
          <div class="feature">
            <div class="feature-icon"><el-icon><Position /></el-icon></div>
            <div>
              <div class="feature-title">轨迹回放</div>
              <div class="feature-desc">第一视角、记忆窗口与几何叠加同步观察</div>
            </div>
          </div>
          <div class="feature">
            <div class="feature-icon"><el-icon><DataAnalysis /></el-icon></div>
            <div>
              <div class="feature-title">诊断分析</div>
              <div class="feature-desc">指标对比、消融矩阵、失败归因与报告导出</div>
            </div>
          </div>
        </div>
      </div>

      <div class="brand-foot">V1.0.0 · 单机部署 · 零外部依赖</div>
    </section>

    <section class="form-side">
      <div class="form-card">
        <h2>登录系统</h2>
        <p class="hint">输入账号口令进入评测工作台</p>

        <el-form :model="form" label-position="top" @submit.prevent="submit">
          <el-form-item label="用户名">
            <el-input
              v-model="form.username"
              size="large"
              placeholder="请输入用户名"
              :prefix-icon="User"
              @keyup.enter="submit"
            />
          </el-form-item>
          <el-form-item label="口令">
            <el-input
              v-model="form.password"
              type="password"
              size="large"
              show-password
              placeholder="请输入口令"
              :prefix-icon="Lock"
              @keyup.enter="submit"
            />
          </el-form-item>

          <el-button
            type="primary"
            size="large"
            class="submit-btn"
            :loading="loading"
            @click="submit"
          >
            进入系统
          </el-button>
        </el-form>

        <div class="tips">
          <div class="tips-title">内置账号</div>
          <div class="tips-row"><span>管理员</span><code>admin / admin123</code></div>
          <div class="tips-row"><span>算法工程师</span><code>operator / operator123</code></div>
          <div class="tips-row"><span>访客</span><code>viewer / viewer123</code></div>
        </div>
      </div>

      <div class="copyright">具身导航多模态流式评测与诊断软件 V1.0</div>
    </section>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Lock, User } from '@element-plus/icons-vue'
import { useAuthStore } from '@/store/auth'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()

const form = reactive({ username: 'admin', password: '' })
const loading = ref(false)

async function submit() {
  if (!form.username || !form.password) {
    ElMessage.warning('请输入用户名与口令')
    return
  }
  loading.value = true
  try {
    await auth.login({ username: form.username.trim(), password: form.password })
    ElMessage.success('登录成功')
    const redirect = typeof route.query.redirect === 'string' ? route.query.redirect : '/overview'
    router.push(redirect)
  } catch {
    // 错误提示由请求拦截器统一处理
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-page {
  display: flex;
  min-height: 100vh;
  background: var(--nav-bg);
}

.brand-side {
  width: 56%;
  min-width: 520px;
  background: var(--nav-sidebar);
  border-right: 1px solid #22344f;
  color: #e8eefb;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  padding: 36px 56px;
}

.brand-top {
  display: flex;
  align-items: center;
  gap: 10px;
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
  font-size: 14px;
  font-weight: 600;
  letter-spacing: 0.3px;
}

.brand-body {
  max-width: 560px;
}

.eyebrow {
  font-size: 12px;
  color: #a9bdd8;
  margin-bottom: 16px;
}

h1 {
  font-size: 34px;
  line-height: 1.35;
  margin: 0 0 18px;
  font-weight: 600;
  letter-spacing: 0.5px;
}

.lede {
  color: #9fb3d1;
  font-size: 14px;
  line-height: 1.9;
  margin: 0 0 34px;
}

.features {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 18px 24px;
}

.feature {
  display: flex;
  gap: 12px;
  align-items: flex-start;
}

.feature-icon {
  width: 32px;
  height: 32px;
  border-radius: 8px;
  background: rgba(79, 140, 255, 0.14);
  color: #6ea4ff;
  display: flex;
  align-items: center;
  justify-content: center;
  flex: 0 0 32px;
}

.feature-title {
  font-size: 13px;
  font-weight: 500;
  color: #dce7f8;
}

.feature-desc {
  font-size: 12px;
  color: #8098bb;
  line-height: 1.6;
  margin-top: 4px;
}

.brand-foot {
  font-size: 11px;
  color: #5d7395;
  letter-spacing: 0.5px;
}

.form-side {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 40px;
  background: var(--nav-panel);
}

.form-card {
  width: 360px;
}

h2 {
  font-size: 22px;
  margin: 0 0 8px;
  font-weight: 600;
}

.hint {
  color: var(--nav-text-muted);
  font-size: 13px;
  margin: 0 0 26px;
}

.submit-btn {
  width: 100%;
  margin-top: 6px;
}

.tips {
  margin-top: 28px;
  padding: 14px 16px;
  border: 1px dashed var(--nav-border-strong);
  border-radius: var(--nav-radius-sm);
  background: #f8fafd;
}

.tips-title {
  font-size: 12px;
  color: var(--nav-text-muted);
  margin-bottom: 8px;
}

.tips-row {
  display: flex;
  justify-content: space-between;
  font-size: 12px;
  color: var(--nav-text-muted);
  line-height: 2;
}

.tips-row code {
  font-family: Consolas, monospace;
  color: #334155;
}

.copyright {
  margin-top: 40px;
  font-size: 11px;
  color: #b3bccb;
}

@media (max-width: 1100px) {
  .brand-side {
    display: none;
  }
}
</style>
