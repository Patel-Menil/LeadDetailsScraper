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
        // BAVRIX palette: navy surfaces, green actions, lime highlights, cream text.
        background: "#061a33",
        surface: "#0b2545",
        card: "#0e2a4d",
        cardHover: "#133459",
        border: "#234a73",
        borderSubtle: "#1a3a5f",
        muted: "#96a6bb",
        dim: "#7186a2",
        white: "#f7f8f0", // cream instead of pure white, per the BAVRIX wordmark
        bavrix: {
          navy: "#08233f",
          deep: "#061a33",
          green: "#00794a",
          leaf: "#4ba35a",
          mint: "#7db86a",
          lime: "#dce450",
          cream: "#f2f3e8",
        },
        // Existing pages use Tailwind's slate/blue/emerald/sky/purple classes; remapping the scales
        // re-themes every page at once. slate = navy neutrals with cream at the top, blue = BAVRIX green
        // (primary actions and links), emerald = success green, sky and purple = lime highlights.
        slate: {
          50: "#f7f8f0", 100: "#f2f3e8", 200: "#dfe4dc", 300: "#c4ccd4", 400: "#96a6bb", 500: "#7186a2",
          600: "#516887", 700: "#2f4a6d", 800: "#1b3557", 900: "#102847", 950: "#071a33",
        },
        blue: {
          50: "#eef7ea", 100: "#d9eecf", 200: "#b6dca2", 300: "#a3d48d", 400: "#7db86a", 500: "#4ba35a",
          600: "#00794a", 700: "#00663f", 800: "#055334", 900: "#08432c", 950: "#032818",
        },
        emerald: {
          50: "#f0f8e9", 100: "#dcefcb", 200: "#bfe2a1", 300: "#b0dc8f", 400: "#8fcf6e", 500: "#5fb85a",
          600: "#2f9a4f", 700: "#237d40", 800: "#1d6435", 900: "#18512d", 950: "#0a2e18",
        },
        sky: {
          50: "#fbfce8", 100: "#f5f8c6", 200: "#eef293", 300: "#e6ec6c", 400: "#dce450", 500: "#c8d136",
          600: "#a3ab22", 700: "#7b821a", 800: "#5c611a", 900: "#4a4e19", 950: "#2a2c08",
        },
        purple: {
          50: "#fbfce8", 100: "#f5f8c6", 200: "#eef293", 300: "#e6ec6c", 400: "#dce450", 500: "#c8d136",
          600: "#a3ab22", 700: "#7b821a", 800: "#5c611a", 900: "#4a4e19", 950: "#2a2c08",
        },
        p0: {
          DEFAULT: "#ef4444",
          bg: "rgba(239, 68, 68, 0.12)",
          border: "rgba(239, 68, 68, 0.3)",
        },
        p1: {
          DEFAULT: "#4ba35a",
          bg: "rgba(75, 163, 90, 0.12)",
          border: "rgba(75, 163, 90, 0.3)",
        },
        p2: {
          DEFAULT: "#64748b",
          bg: "rgba(100, 116, 139, 0.12)",
          border: "rgba(100, 116, 139, 0.3)",
        },
        success: {
          DEFAULT: "#5fb85a",
          bg: "rgba(95, 184, 90, 0.12)",
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
