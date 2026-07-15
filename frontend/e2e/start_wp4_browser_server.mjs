import process from 'node:process';
import { fileURLToPath } from 'node:url';

process.env.VITE_RAG_INSPECTOR_DEV_ACCESS_TOKEN = 'wp4-local-browser-token';
process.env.VITE_RAG_INSPECTOR_DEV_USER_ID = 'wp4-browser-user';
process.env.VITE_RAG_INSPECTOR_DEV_EMAIL = 'wp4-browser@example.test';

process.chdir(fileURLToPath(new URL('..', import.meta.url)));
process.argv = [
  process.execPath,
  'vite',
  '--host',
  '127.0.0.1',
  '--port',
  '4273',
  '--strictPort',
];

await import('../node_modules/vite/bin/vite.js');
