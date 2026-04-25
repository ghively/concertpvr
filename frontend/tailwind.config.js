export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        terracotta: { DEFAULT: "#d4664a", dim: "#a84e37" },
        sage: { DEFAULT: "#7ab078", dim: "#55805a" },
        amber: { DEFAULT: "#d4a35a", dim: "#9f7a3e" },
        mauve: { DEFAULT: "#9b7dd4", dim: "#6d56a0" },
        surface: {
          0: "#0c0e12",
          1: "#14171c",
          2: "#1a1d24",
          3: "#232730",
        },
        border: {
          DEFAULT: "#2a2e36",
          strong: "#353a46",
        },
        ink: {
          DEFAULT: "#e8eaee",
          dim: "#9aa0ab",
          faint: "#6b7280",
        },
      },
      fontFamily: {
        mono: ["JetBrains Mono", "ui-monospace", "Menlo", "monospace"],
      },
    },
  },
  plugins: [],
};
