import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { VitePWA } from 'vite-plugin-pwa'

const rawBuildId = process.env.FRONTEND_BUILD_ID?.trim() || 'local'
const serviceWorkerBuildId = rawBuildId.replace(/[^A-Za-z0-9._-]/g, '-') || 'local'
const serviceWorkerUrl = `/sw.js?v=${encodeURIComponent(serviceWorkerBuildId)}`

const versionedServiceWorkerRegistration = {
  name: 'versioned-service-worker-registration',
  transformIndexHtml() {
    return [
      {
        tag: 'script',
        attrs: { id: 'finsight-service-worker-registration' },
        children: `if ('serviceWorker' in navigator) { window.addEventListener('load', () => { navigator.serviceWorker.register(${JSON.stringify(serviceWorkerUrl)}, { scope: '/' }) }) }`,
        injectTo: 'head' as const,
      },
    ]
  },
}

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: 'autoUpdate',
      injectRegister: false,
      includeAssets: ['favicon.svg', 'logo.svg'],
      manifest: {
        name: 'FinSight AI',
        short_name: 'FinSight',
        description: 'AI 驱动的金融研究与投资分析工作台',
        theme_color: '#FF8A00',
        background_color: '#0D1117',
        display: 'standalone',
        start_url: '/',
        scope: '/',
        lang: 'zh-CN',
        icons: [
          {
            src: '/logo.svg',
            sizes: 'any',
            type: 'image/svg+xml',
            purpose: 'any',
          },
          {
            src: '/logo.svg',
            sizes: 'any',
            type: 'image/svg+xml',
            purpose: 'maskable',
          },
        ],
      },
      workbox: {
        navigateFallbackDenylist: [/^\/api\//],
        runtimeCaching: [
          {
            // API（包括 SSE）始终直连网络，禁止进入 Service Worker 缓存。
            urlPattern: ({ url }) => url.pathname.startsWith('/api/'),
            handler: 'NetworkOnly',
          },
          {
            urlPattern: ({ request, url }) =>
              !url.pathname.startsWith('/api/')
              && ['style', 'script', 'worker', 'font', 'image'].includes(request.destination),
            handler: 'CacheFirst',
            options: {
              cacheName: 'finsight-static-assets',
              expiration: {
                maxEntries: 128,
                maxAgeSeconds: 30 * 24 * 60 * 60,
              },
            },
          },
        ],
      },
    }),
    versionedServiceWorkerRegistration,
  ],
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
