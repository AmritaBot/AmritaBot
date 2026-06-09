/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: 'class',
  content: [
    './amrita/**/templates/**/*.html',
    './plugins/**/templates/**/*.html',
  ],
  theme: {
    extend: {
      colors: {
        primary: {
          DEFAULT: '#3498db',
          hover: '#2980b9',
        },
        accent: {
          DEFAULT: '#1abc9c',
          hover: '#16a085',
        },
        danger: {
          DEFAULT: '#e74c3c',
          hover: '#c0392b',
        },
        success: {
          DEFAULT: '#27ae60',
          hover: '#219a52',
        },
        sidebar: {
          DEFAULT: '#2c3e50',
          hover: '#34495e',
          dark: '#121212',
          'dark-hover': '#1e1e1e',
        },
        dark: {
          bg: '#1a1a1a',
          card: '#252525',
          header: '#2d2d2d',
          border: '#444',
        },
      },
      fontFamily: {
        sans: ['"Segoe UI"', '"Microsoft YaHei"', 'sans-serif'],
      },
      backdropBlur: {
        glass: '10px',
      },
    },
  },
  plugins: [],
}
