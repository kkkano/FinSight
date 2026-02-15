/** @type {import('tailwindcss').Config} */
export default {
  darkMode: 'class',
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      fontSize: {
        '2xs': ['11px', { lineHeight: '16px' }],
      },
      colors: {
        fin: {
          bg: 'var(--fin-bg)',
          'bg-secondary': 'var(--fin-bg-secondary)',
          card: 'var(--fin-card)',
          panel: 'var(--fin-panel)',
          border: 'var(--fin-border)',
          hover: 'var(--fin-hover)',
          text: 'var(--fin-text)',
          'text-secondary': 'var(--fin-text-secondary)',
          muted: 'var(--fin-muted)',
          primary: 'rgb(var(--fin-primary) / <alpha-value>)',
          success: 'var(--fin-success)',
          danger: 'var(--fin-danger)',
          warning: 'var(--fin-warning)',
          predict: 'var(--fin-predict)',
        },
        trend: {
          up: 'var(--fin-success)',
          down: 'var(--fin-danger)',
        }
      },
      fontFamily: {
        sans: ['-apple-system', '"PingFang SC"', '"Microsoft YaHei"', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'ui-monospace', 'SFMono-Regular', 'Menlo', 'Monaco', 'Consolas', 'monospace'],
      },
      animation: {
        'fade-in': 'fadeIn 0.3s ease-out',
        'slide-up': 'slideUp 0.4s ease-out',
        'slide-in-right': 'slideInRight 0.3s ease-out',
        'fade-out': 'fadeOut 0.25s ease-in forwards',
      },
      keyframes: {
        fadeIn: {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
        slideUp: {
          '0%': { transform: 'translateY(20px)', opacity: '0' },
          '100%': { transform: 'translateY(0)', opacity: '1' },
        },
        slideInRight: {
          '0%': { transform: 'translateX(100%)', opacity: '0' },
          '100%': { transform: 'translateX(0)', opacity: '1' },
        },
        fadeOut: {
          '0%': { opacity: '1', transform: 'translateX(0)' },
          '100%': { opacity: '0', transform: 'translateX(30%)' },
        },
      }
    },
  },
  plugins: [
    require('@tailwindcss/typography'),
  ],
}
