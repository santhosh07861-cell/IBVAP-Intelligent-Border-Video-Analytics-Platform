/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        dark: {
          900: '#0a0d14',
          800: '#111622',
          700: '#1a2030',
          600: '#252d42',
          500: '#333e5b'
        },
        border: {
          alert: '#ef4444',
          warning: '#f97316',
          safe: '#10b981',
          accent: '#3b82f6'
        }
      }
    },
  },
  plugins: [],
}
