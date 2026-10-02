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
        '2xs': ['12px', { lineHeight: '18px' }],
      },
      colors: {
        t: {
          bg: 'var(--t-bg)', surface: 'var(--t-surface)', card: 'var(--t-card)',
          elevated: 'var(--t-elevated)', border: 'rgb(var(--t-border-rgb) / <alpha-value>)', divider: 'rgb(var(--t-divider-rgb) / <alpha-value>)',
          hover: 'rgb(var(--t-hover-rgb) / <alpha-value>)', text: 'var(--t-text)', text2: 'var(--t-text-2)', text3: 'var(--t-text-3)',
          accent: 'rgb(var(--t-accent) / <alpha-value>)', 'accent-hi': 'var(--t-accent-hi)',
          up: 'rgb(var(--t-up-rgb) / <alpha-value>)', down: 'rgb(var(--t-down-rgb) / <alpha-value>)',
          warning: 'rgb(var(--t-warning-rgb) / <alpha-value>)', info: 'rgb(var(--t-info-rgb) / <alpha-value>)',
          predict: 'rgb(var(--t-predict-rgb) / <alpha-value>)',
        },
        fin: {
          bg: 'var(--fin-bg)',
          'bg-secondary': 'var(--fin-bg-secondary)',
          card: 'var(--fin-card)',
          panel: 'var(--fin-panel)',
          border: 'rgb(var(--t-border-rgb) / <alpha-value>)',
          hover: 'rgb(var(--t-hover-rgb) / <alpha-value>)',
          text: 'var(--fin-text)',
          'text-secondary': 'var(--fin-text-secondary)',
          muted: 'var(--fin-muted)',
          primary: 'rgb(var(--fin-primary) / <alpha-value>)',
          success: 'rgb(var(--t-up-rgb) / <alpha-value>)',
          danger: 'rgb(var(--t-down-rgb) / <alpha-value>)',
          warning: 'rgb(var(--t-warning-rgb) / <alpha-value>)',
          predict: 'rgb(var(--t-predict-rgb) / <alpha-value>)',
        },
        trend: {
          up: 'rgb(var(--t-up-rgb) / <alpha-value>)',
          down: 'rgb(var(--t-down-rgb) / <alpha-value>)',
        }
      },
      fontFamily: {
        sans: ['-apple-system', '"PingFang SC"', '"Microsoft YaHei"', 'system-ui', 'sans-serif'],
        mono: ['"JetBrains Mono Variable"', 'JetBrains Mono', 'ui-monospace', 'SFMono-Regular', 'Menlo', 'Monaco', 'Consolas', 'monospace'],
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
