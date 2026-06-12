/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        primary: {
          DEFAULT: '#2563eb',
          bg: '#eff6ff',
        },
        success: {
          DEFAULT: '#16a34a',
          bg: '#f0fdf4',
        },
        warning: {
          DEFAULT: '#d97706',
          bg: '#fffbeb',
        },
        danger: {
          DEFAULT: '#dc2626',
          bg: '#fef2f2',
        },
        border: '#e5e7eb',
        bgMain: '#f9fafb',
        textMain: '#111827',
        textMuted: '#6b7280',
      }
    },
  },
  plugins: [],
}
