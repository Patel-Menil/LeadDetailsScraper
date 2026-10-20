/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: ["class"],
  content: [
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        background: "#0a0d14",
        surface: "#101522",
        card: "#151b2c",
        cardHover: "#1b2339",
        border: "#232c45",
        borderSubtle: "#1c2438",
        muted: "#94a3b8",
        dim: "#64748b",
        p0: {
          DEFAULT: "#ef4444",
          bg: "rgba(239, 68, 68, 0.12)",
          border: "rgba(239, 68, 68, 0.3)",
        },
        p1: {
          DEFAULT: "#3b82f6",
          bg: "rgba(59, 130, 246, 0.12)",
          border: "rgba(59, 130, 246, 0.3)",
        },
        p2: {
          DEFAULT: "#64748b",
          bg: "rgba(100, 116, 139, 0.12)",
          border: "rgba(100, 116, 139, 0.3)",
        },
        success: {
          DEFAULT: "#10b981",
          bg: "rgba(16, 185, 129, 0.12)",
        },
        warning: {
          DEFAULT: "#f59e0b",
          bg: "rgba(245, 158, 11, 0.12)",
        },
      },
    },
  },
  plugins: [],
};
