# C-9 `/api/supabase` 前端残留盘点

## 结论

全仓没有任何请求发往 FinSight 后端 `/api/supabase`。原盘点命令命中的 4 处均是 TypeScript 模块导入路径中的连续字符串，例如 `./api/supabaseClient` 与 `../../api/supabaseClient`，不是 URL。

## 逐处语义

| 文件 | 用途 | 判定 |
|---|---|---|
| `frontend/src/App.tsx` | 读取官方 Supabase SDK 会话，保护需登录路由 | 保留 |
| `frontend/src/components/welcome/WelcomePage.tsx` | 邮箱 OTP 登录与会话建立 | 保留 |
| `frontend/src/components/welcome/WelcomePage.test.tsx` | mock 同一前端模块 | 保留 |
| `frontend/src/api/http.ts` | 从 SDK session 提取 Bearer token，附加到 FinSight API 请求 | 保留 |

`frontend/src/api/supabaseClient.ts` 使用 `@supabase/supabase-js` 的 `createClient(SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY)` 直连 Supabase Auth。FinSight 后端没有 `/api/supabase` router；它只在安全门读取并校验 Bearer token。因此没有死 UI 分支或不存在的后端调用需要删除。

为防止再次误判，已在 `supabaseClient.ts` 增加中文模块注释，明确“模块路径不是后端端点”。
