import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/store/auth'

const routes = [
  {
    path: '/login',
    name: 'login',
    component: () => import('@/views/Login.vue'),
    meta: { public: true, title: '登录' },
  },
  {
    path: '/',
    component: () => import('@/layouts/DefaultLayout.vue'),
    redirect: '/overview',
    children: [
      {
        path: 'overview',
        name: 'overview',
        component: () => import('@/views/Overview.vue'),
        meta: { title: '总览', subtitle: '评测资产与运行状态一览' },
      },
      {
        path: 'datasets',
        name: 'datasets',
        component: () => import('@/views/dataset/List.vue'),
        meta: { title: '数据集' },
      },
      {
        path: 'datasets/:id',
        name: 'dataset-detail',
        component: () => import('@/views/dataset/Detail.vue'),
        meta: { title: '数据集详情' },
      },
      {
        path: 'models',
        name: 'models',
        component: () => import('@/views/model/List.vue'),
        meta: { title: '模型档案' },
      },
      {
        path: 'tasks',
        name: 'tasks',
        component: () => import('@/views/task/List.vue'),
        meta: { title: '评测任务' },
      },
      {
        path: 'tasks/:id',
        name: 'task-detail',
        component: () => import('@/views/task/Detail.vue'),
        meta: { title: '任务监控' },
      },
      {
        path: 'analysis',
        name: 'analysis',
        component: () => import('@/views/analysis/Index.vue'),
        meta: { title: '结果分析', subtitle: '指标对比、消融与失败诊断' },
      },
      {
        path: 'replay',
        name: 'replay',
        component: () => import('@/views/replay/Workbench.vue'),
        meta: { title: '轨迹回放', subtitle: '四区联动的逐帧回放工作台' },
      },
      {
        path: 'sim',
        name: 'sim',
        component: () => import('@/views/sim/Workbench.vue'),
        meta: { title: '交互式仿真', subtitle: '在场景里手动驾驶机器狗，实时看第一视角与轨迹' },
      },
      {
        path: 'reports',
        name: 'reports',
        component: () => import('@/views/report/Center.vue'),
        meta: { title: '报告中心', subtitle: '分析报告与指标矩阵导出' },
      },
      {
        path: 'backup-import',
        name: 'backup-import',
        component: () => import('@/views/system/BackupImport.vue'),
        meta: { title: '备份库导入', subtitle: '自动同步数据集、模型档案与评测资料' },
      },
      {
        path: 'settings',
        name: 'settings',
        component: () => import('@/views/system/Settings.vue'),
        meta: { title: '系统设置', subtitle: '运行参数与系统状态' },
      },
      {
        path: 'users',
        name: 'users',
        component: () => import('@/views/system/Users.vue'),
        meta: { title: '用户管理', admin: true },
      },
      {
        path: 'audit',
        name: 'audit',
        component: () => import('@/views/system/Audit.vue'),
        meta: { title: '操作审计', admin: true },
      },
    ],
  },
  { path: '/:pathMatch(.*)*', redirect: '/overview' },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach((to) => {
  const auth = useAuthStore()
  if (!to.meta.public && !auth.isLoggedIn) {
    return { path: '/login', query: { redirect: to.fullPath } }
  }
  if (to.meta.public && auth.isLoggedIn && to.path === '/login') {
    return { path: '/overview' }
  }
  if (to.meta.admin && auth.role !== 'admin') {
    return { path: '/overview' }
  }
  document.title = to.meta.title
    ? `${to.meta.title} · NavEval Studio`
    : '具身导航多模态流式评测与诊断软件 V1.0'
  return true
})

export default router
