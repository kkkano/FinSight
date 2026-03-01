import { createClient, type SupabaseClient } from '@supabase/supabase-js';
import { SUPABASE_AUTH_ENABLED, SUPABASE_PUBLISHABLE_KEY, SUPABASE_URL } from '../config/runtime';

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
