# AdminUI 回归基线（阶段 0）

> AdminUI 2.0 界面层重写前的行为快照，作为后续逐阶段迁移的对照基线。
> 全部内容基于重写前源码核实（AdminUI v0.1.45，`AdminUI/src`）。

## 1. 登录流程

App.vue 根组件三态门（`AdminUI/src/App.vue`）：

1. `!authStore.initialized` → 全屏 `boot-loading`（NSpin）；
2. `!isAuthenticated` → 渲染 `LoginView`（就地渲染，不发生路由跳转）；
3. `isAuthenticated && !adminAccess` → 403 页（"当前账户没有管理权限"，normal 用户止步于此）；
4. 否则 → `AdminLayout` + `router-view`（`MfaStepUpModal` 挂在 AdminLayout 内）。

关键链路：

- **发起登录**（`stores/auth.ts` `startLogin`）：整页跳转 `GET /api/admin/bff/login?returnUrl=/admin/`（OAuth BFF）；`starting` 防重复点击。
- **登录回跳**（`init`）：读取 `?error=`（`access_denied`→"登录已取消"）；否则 `GET /api/admin/capabilities` 恢复身份（401 → 清空本地态回落登录页），已登录再 `GET /api/auth/mfa/status` + 预热用户域 CSRF token。
- **登出**：`POST /api/auth/logout`（用户域 CSRF），**失败抛错不静默刷新**；成功后清空本地态并硬跳转 `/admin/login`。
- **CSRF 双提交**：`/api/admin/*` 写请求内存 token ↔ `Pylaios.AdminCsrf` Cookie；403 `csrf_invalid` 补签重放一次；`/api/auth/*` 走用户域 `userCsrfFetch`。认证/CSRF/MFA 核心逻辑本阶段不重写。

## 2. 三角色行为差异

前端**不硬编码角色判断**，一切来自 `GET /api/admin/capabilities`（每项含 `key/name/description/route/canEditGroup/canEditStatus/targetGroups/endpoints[]`）。

| 角色 | 行为 |
| --- | --- |
| normal | `adminAccess=false` → 直接 403 页，看不到任何管理页面 |
| admin | capabilities 决定可见模块；`canEditStatus/canEditGroup/targetGroups` 为 false/空时隐藏用户状态与组编辑；行内操作按钮按 `endpoints` 显隐 |
| max | 全部 capability 字段为真：用户状态/组编辑、注册策略开关、全部管理端点 |

- 编辑用户时仅当 `canEditStatus/canEditGroup` 为 true 才把 `status/group` 放进 PATCH body（与"设置 Admin/Max 组仅限 Max"对应）。
- 导航分组：身份与接入 = users/inviteCodes/clients；安全与治理 = bans/auditLogs；概览与账户安全对所有 adminAccess 用户可见。

## 3. MFA Step-up 触发点

所有页面请求统一走 `authStore.request()`；捕获 `mfa_step_up_required` 自动弹出 `MfaStepUpModal`（mask 不可点关、Esc 不可关），完成后**自动重放原请求一次**，并发共享同一 Promise。弹窗内 TOTP（6 位）与 WebAuthn/Passkey 两种方法按 `methods` 渲染。

可能触发 Step-up 的写操作（以代码调用点为准，实际是否要求由后端决定）：

- **用户管理**：编辑用户（含改组）、封禁/锁定/启用、重置密码、吊销单个/全部会话、吊销 UserToken、硬删除（软删除明确无需 MFA）
- **邀请码**：注册策略开关、创建、编辑、撤销
- **封禁管理**：按 ID 解封、按 IP 解封
- **OAuth2 客户端**：创建、更新（含密钥轮换）、启用/禁用、Logo 上传/删除、删除客户端
- **账户安全（自我管理）**：TOTP 注册、Passkey 注册/重命名/删除

## 4. 各页面关键操作

| 页面 | 关键操作 |
| --- | --- |
| 概览 `/` | 展示当前管理员/权限组/可用模块/注册策略；模块入口列表；无写操作 |
| 用户管理 `/users` | 筛选（搜索/组/状态）+ 分页；行内：详情、编辑、封禁/锁定/启用、更多（重置密码/会话/Token/删除）；删除二级弹窗（软/硬） |
| 邀请码 `/invite-codes` | 注册策略开关（写入后回读校验）；按目标组筛选；创建（admin/max 强制单次核销）；完整码仅显示一次；编辑/详情/撤销 |
| 封禁管理 `/bans` | 当前封禁/历史两个 Tab；按来源筛选；行内解封；按 IP 解封 |
| 审计日志 `/audit-logs` | 只读检索：事件类型/用户/IP/结果/时间范围；无写操作 |
| OAuth2 客户端 `/clients` | 添加客户端 4 步向导（本地校验 + 前端生成 Secret）；编辑；启停；Logo 上传/删除；删除 |
| 账户安全 `/security` | MFA 状态四态徽章；TOTP 设置（QR+确认）；Passkey 添加/重命名/删除 |

## 5. 现状已知问题（重写对照点）

- 各列表 `load()` 失败后 toast 报错并落 `[]`，**加载失败与"没有数据"视觉不可区分**（StateBlock 的目标场景）。
- `loadMfaCredentials` 失败静默置空，表现为"没有 Passkey"。
- 详情弹窗加载失败直接关闭弹窗。
- 移动端侧栏只是 `.open` class 平移，无焦点圈定/Esc/焦点还原/aria/滚动锁。
- 未知路由静默跳首页（应为 404）。
- 被守卫踢回首页后丢失原始目标 URL。
- 顶栏与 PageHeader 重复页面标题。
- `--text-tertiary: #8a9199` 白底对比度 3.19:1，不达标。
- 内置 12.5MB webfont（全局 UI 与 mono 混用 AppFont）。
