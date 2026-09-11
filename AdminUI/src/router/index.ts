import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const HomeView = () => import('@/views/HomeView.vue')
const UsersView = () => import('@/views/UsersView.vue')
const InviteCodesView = () => import('@/views/InviteCodesView.vue')
const BansView = () => import('@/views/BansView.vue')
const AuditLogsView = () => import('@/views/AuditLogsView.vue')
const ClientsView = () => import('@/views/ClientsView.vue')
const SecurityView = () => import('@/views/SecurityView.vue')

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    { path: '/', name: 'home', component: HomeView, meta: { pageTitle: '概览' } },
    { path: '/users', name: 'users', component: UsersView, meta: { pageTitle: '用户管理', capability: 'users' } },
    { path: '/invite-codes', name: 'invite-codes', component: InviteCodesView, meta: { pageTitle: '邀请码', capability: 'inviteCodes' } },
    { path: '/clients', name: 'clients', component: ClientsView, meta: { pageTitle: 'OAuth2 客户端', capability: 'clients' } },
    { path: '/bans', name: 'bans', component: BansView, meta: { pageTitle: '封禁管理', capability: 'bans' } },
    { path: '/audit-logs', name: 'audit-logs', component: AuditLogsView, meta: { pageTitle: '审计日志', capability: 'auditLogs' } },
    { path: '/security', name: 'security', component: SecurityView, meta: { pageTitle: '账户安全' } },
    { path: '/:pathMatch(.*)*', redirect: '/' }
  ]
})

router.beforeEach((to) => {
  const capability = to.meta.capability as string | undefined
  if (capability) {
    const authStore = useAuthStore()
    if (!authStore.isAuthenticated || !authStore.hasCapability(capability)) {
      return { name: 'home' }
    }
  }
  const pageTitle = String(to.meta.pageTitle || 'Pylai Admin')
  document.title = pageTitle === 'Pylai Admin' ? pageTitle : `${pageTitle} · Pylai Admin`
})

export default router
