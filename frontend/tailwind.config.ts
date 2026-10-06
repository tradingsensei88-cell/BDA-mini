import type { Config } from "tailwindcss";

/**
 * CyberShield AI design tokens.
 *
 * Loaded by `app/globals.css` through the Tailwind v4 `@config` directive,
 * so every token below is available as a utility class (e.g. `bg-cyber-bg`,
 * `text-severity-critical`, `shadow-glow-accent`, `animate-pulse-glow`).
 */
const config: Config = {
  darkMode: "class",
  content: [
    "./app/**/*.{ts,tsx,mdx}",
    "./components/**/*.{ts,tsx}",
    "./features/**/*.{ts,tsx}",
    "./hooks/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        /** Core surfaces - deep navy command-center palette. */
        cyber: {
          bg: "#04070F",          // page background (near-black navy)
          surface: "#080E1C",     // cards / panels
          elevated: "#0D1628",    // raised surfaces (modals, popovers)
          overlay: "#111C33",     // hover states / overlays
          border: "#17233D",      // hairline borders
          grid: "#0F1A30",        // background grid lines
          muted: "#8FA3BF",       // secondary text
          accent: "#22D3EE",      // primary cyan accent
          "accent-bright": "#67E8F9",
          "accent-dim": "#0E7490",
          teal: "#2DD4BF",        // secondary teal accent
        },
        /** Attack severity scale used across alerts, charts, and badges. */
        severity: {
          critical: "#FF3B5C",
          high: "#FF8A3D",
          medium: "#FFD166",
          low: "#34D399",
          info: "#60A5FA",
        },
      },
      fontFamily: {
        sans: ["var(--font-inter)", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: [
          "var(--font-jetbrains-mono)",
          "ui-monospace",
          "SFMono-Regular",
          "monospace",
        ],
      },
      boxShadow: {
        "glow-accent": "0 0 24px -4px rgba(34, 211, 238, 0.45)",
        "glow-critical": "0 0 24px -4px rgba(255, 59, 92, 0.45)",
        "glow-low": "0 0 24px -4px rgba(52, 211, 153, 0.45)",
        panel:
          "inset 0 1px 0 0 rgba(255, 255, 255, 0.03), 0 8px 32px -12px rgba(0, 0, 0, 0.6)",
      },
      backgroundImage: {
        "cyber-grid":
          "linear-gradient(to right, rgba(34, 211, 238, 0.05) 1px, transparent 1px), linear-gradient(to bottom, rgba(34, 211, 238, 0.05) 1px, transparent 1px)",
        "cyber-radial":
          "radial-gradient(ellipse 80% 50% at 50% -20%, rgba(34, 211, 238, 0.12), transparent)",
      },
      backgroundSize: {
        grid: "32px 32px",
      },
      keyframes: {
        "pulse-glow": {
          "0%, 100%": {
            opacity: "1",
            boxShadow: "0 0 0 0 rgba(34, 211, 238, 0.55)",
          },
          "50%": {
            opacity: "0.85",
            boxShadow: "0 0 0 8px rgba(34, 211, 238, 0)",
          },
        },
        "scan-line": {
          "0%": { transform: "translateY(-100%)" },
          "100%": { transform: "translateY(100vh)" },
        },
        ticker: {
          "0%": { transform: "translateX(0)" },
          "100%": { transform: "translateX(-50%)" },
        },
        "fade-up": {
          "0%": { opacity: "0", transform: "translateY(12px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
      },
      animation: {
        "pulse-glow": "pulse-glow 2.4s ease-in-out infinite",
        "scan-line": "scan-line 7s linear infinite",
        ticker: "ticker 30s linear infinite",
        "fade-up": "fade-up 0.6s cubic-bezier(0.22, 1, 0.36, 1) both",
      },
    },
  },
  plugins: [],
};

export default config;
