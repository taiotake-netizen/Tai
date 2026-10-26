import type { Config } from "tailwindcss";

export default {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: "#0b0f17",
        panel: "#121826",
        panel2: "#182033",
        line: "#263049",
        gold: "#e9b949",
        up: "#26a69a",
        down: "#ef5350",
        flat: "#8a94a8",
        muted: "#8a94a8",
      },
      fontFamily: { sans: ["Hiragino Sans", "Noto Sans JP", "Yu Gothic", "system-ui", "sans-serif"] },
    },
  },
  plugins: [],
} satisfies Config;
