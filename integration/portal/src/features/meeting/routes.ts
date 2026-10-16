import type { RouteRecordRaw } from 'vue-router'

const enabled = import.meta.env.VITE_MEETING_ENABLED === 'true'
const routes: RouteRecordRaw[] = enabled ? [
  { path: '/meeting', redirect: '/meeting/overview', meta: { requiresAuth: true } },
  { path: '/meeting/authorize', name: 'MeetingAuthorization', component: () => import('./MeetingConsent.vue'), meta: { requiresAuth: true } },
  { path: '/meeting/:section', name: 'MeetingConsole', component: () => import('./MeetingConsole.vue'), meta: { requiresAuth: true } },
] : []
export default routes
