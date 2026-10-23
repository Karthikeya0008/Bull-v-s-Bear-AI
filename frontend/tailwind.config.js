/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bull: { DEFAULT: "#22c55e", soft: "#052e16" },
        bear: { DEFAULT: "#ef4444", soft: "#450a0a" },
      },
    },
  },
  plugins: [],
};
