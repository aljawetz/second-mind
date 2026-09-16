import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Fixed port + strictPort: Tauri's devUrl points at a known address, so the
// dev server must fail loudly on a port conflict rather than silently pick
// another port Tauri isn't looking at.
export default defineConfig({
  plugins: [react()],
  clearScreen: false,
  server: {
    port: 1420,
    strictPort: true,
  },
});
