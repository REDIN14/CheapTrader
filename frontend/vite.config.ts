import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // changeOrigin stays off on purpose: the program refuses a request whose Origin (this page,
      // localhost:5173) is not the Host it was sent to, which is how it keeps other web pages out.
      // A proxy that rewrites the Host header (Vite's shorthand "/api": "http://..." does) would
      // make this page one of those. To serve the page from another address, list it in
      // CT_ALLOWED_ORIGINS (backend/.env) instead.
      "/api": { target: "http://localhost:8000", changeOrigin: false },
      "/ws": {
        target: "ws://localhost:8000",
        ws: true,
      },
    },
    watch: {
      // Editors that write atomically drop a locked temp file in a hidden
      // `.tmpdir` folder next to the target. Watching that folder makes Node's
      // fs watcher throw EBUSY and takes the dev server down with it, so it is
      // excluded here.
      ignored: ["**/.*.tmpdir/**", "**/*.tmp", "**/.git/**"],
    },
  },
});
