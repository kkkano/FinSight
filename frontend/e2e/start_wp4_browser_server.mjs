import process from 'node:process';
import { fileURLToPath } from 'node:url';

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
