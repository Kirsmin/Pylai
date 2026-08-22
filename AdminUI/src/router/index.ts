import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
const HomeView = () => import('@/views/HomeView.vue')
const UsersView = () => import('@/views/UsersView.vue')
const InviteCodesView = () => import('@/views/InviteCodesView.vue')
const BansView = () => import('@/views/BansView.vue')
const AuditLogsView = () => import('@/views/AuditLogsView.vue')
const ClientsView = () => import('@/views/ClientsView.vue')

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    { path: '/', name: 'home', component: HomeView, meta: { title: '# Pylai' } },
    { path: '/users', name: 'users', component: UsersView, meta: { title: 'Pylai 用户管理', capability: 'users' } },
    { path: '/invite-codes', name: 'invite-codes', component: InviteCodesView, meta: { title: 'Pylai 邀请码', capability: 'inviteCodes' } },
    { path: '/bans', name: 'bans', component: BansView, meta: { title: 'Pylai 封禁管理', capability: 'bans' } },
    { path: '/audit-logs', name: 'audit-logs', component: AuditLogsView, meta: { title: 'Pylai 审计日志', capability: 'auditLogs' } },
    { path: '/clients', name: 'clients', component: ClientsView, meta: { title: 'Pylai 客户端管理', capability: 'clients' } },
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
  document.title = to.meta.title as string || 'Pylai'
})

export default router
