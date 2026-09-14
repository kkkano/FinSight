import { createClient, type SupabaseClient } from '@supabase/supabase-js';
import { SUPABASE_AUTH_ENABLED, SUPABASE_PUBLISHABLE_KEY, SUPABASE_URL } from '../config/runtime';

// 本模块通过官方 SDK 直连 SUPABASE_URL；`./api/supabaseClient` 只是前端模块路径，
// 不是 FinSight 后端的 `/api/supabase` 端点。后端只校验 SDK 签发的 Bearer token。

let singletonClient: SupabaseClient | null = null;

export const isSupabaseAuthConfigured = (): boolean => SUPABASE_AUTH_ENABLED;

export const getSupabaseClient = (): SupabaseClient | null => {
  if (!SUPABASE_URL || !SUPABASE_PUBLISHABLE_KEY) return null;
  if (!singletonClient) {
    singletonClient = createClient(SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY, {
      auth: {
        persistSession: true,
        autoRefreshToken: true,
        detectSessionInUrl: true,
      },
    });
  }
  return singletonClient;
};
