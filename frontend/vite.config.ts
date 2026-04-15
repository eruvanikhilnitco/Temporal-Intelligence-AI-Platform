import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "0.0.0.0",
    port: 5173,
    strictPort: true,
    // Allow GitHub Codespace subdomains (*.app.github.dev) and any other host
    allowedHosts: "all",
    proxy: {
      "/auth":       { target: "http://localhost:8000", changeOrigin: true },
      "/ask":        { target: "http://localhost:8000", changeOrigin: true },
      "/upload":     { target: "http://localhost:8000", changeOrigin: true },
      "/health":     { target: "http://localhost:8000", changeOrigin: true },
      "/admin":      { target: "http://localhost:8000", changeOrigin: true },
      "/chat":       { target: "http://localhost:8000", changeOrigin: true },
      "/feedback":   { target: "http://localhost:8000", changeOrigin: true },
      "/sharepoint": { target: "http://localhost:8000", changeOrigin: true },
      "/website":    { target: "http://localhost:8000", changeOrigin: true },
    },
  },
});
