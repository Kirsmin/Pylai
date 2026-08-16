import { createRouter, createWebHistory } from 'vue-router'
import Home from '@/views/Home.vue'
import About from '@/views/About.vue'
import Register from '@/views/Register.vue'
import Login from '@/views/Login.vue'
import AuthWithPylai from '@/views/AuthWithPylai.vue'
import ForgetPassword from '@/views/ForgetPassword.vue'
import ResetPassword from '@/views/ResetPassword.vue'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/',
      name: 'home',
      component: Home,
      meta: { title: '—— Pylai ——' },
    },
    {
      path: '/about',
      name: 'about',
      component: About,
      meta: { title: 'Pylai ?' },
    },
    {
      path: '/register',
      name: 'register',
      component: Register,
      meta: { title: '<< Pylai！' },
    },
    {
      path: '/login',
      name: 'login',
      component: Login,
      meta: { title: '> Pylai <' },
    },
    {
      path: '/login/ResetPassword',
      name: 'reset-password',
      component: ResetPassword,
      meta: { title: 'Py >***< lai' },
    },
    {
      path: '/ForgetPassword',
      name: 'forget-password',
      component: ForgetPassword,
      meta: { title: 'Pylai 重置密码' },
    },
    {
      path: '/auth-with-pylai',
      name: 'auth-with-pylai',
      component: AuthWithPylai,
      meta: { title: 'Pylai 授权' },
    },
  ],
})

router.beforeEach((to) => {
  document.title = to.meta.title as string || 'Pylai'
})

export default router
