/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "-apple-system", "Segoe UI", "sans-serif"],
      },
      colors: {
        brand: { DEFAULT: "#1e3a8a", dark: "#172f6e", light: "#eef2ff" },
        bull: { DEFAULT: "#059669", dark: "#047857", soft: "#ecfdf5", line: "#a7f3d0" },
        bear: { DEFAULT: "#e11d48", dark: "#be123c", soft: "#fff1f2", line: "#fecdd3" },
        page: "#f5f7fa",
      },
      boxShadow: {
        card: "0 1px 2px rgba(15, 23, 42, 0.04), 0 1px 3px rgba(15, 23, 42, 0.06)",
        pop: "0 10px 30px rgba(15, 23, 42, 0.12)",
      },
    },
  },
  plugins: [],
};
