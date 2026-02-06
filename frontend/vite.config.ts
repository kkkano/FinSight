import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  define: {
    'process.env': {}
  },
  build: {
    // ECharts is intentionally kept in its own vendor chunk; raise warning limit
    // so build output reflects actionable warnings only.
    chunkSizeWarningLimit: 1500,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes('node_modules')) return

          if (id.includes('react-dom') || id.includes('react-router-dom') || id.includes('react')) {
            return 'vendor-react'
          }
          if (id.includes('echarts')) {
            return 'vendor-echarts'
          }
          if (
            id.includes('react-markdown') ||
            id.includes('remark-gfm') ||
            id.includes('/remark-') ||
            id.includes('/rehype-') ||
            id.includes('/unified') ||
            id.includes('/mdast-')
          ) {
            return 'vendor-markdown'
          }
          if (id.includes('framer-motion')) {
            return 'vendor-motion'
          }
          if (id.includes('lucide-react')) {
            return 'vendor-icons'
          }
          return 'vendor-misc'
        },
      },
    },
  },
})
