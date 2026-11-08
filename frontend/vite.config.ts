import { fileURLToPath, URL } from "node:url";

import react from "@vitejs/plugin-react";
// vitest/config, not vite: this file also carries the test block.
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  server: {
    port: 5173,
    strictPort: true,
    // The API is a separate origin in production, so it is a separate origin
    // here too — credentialed CORS is exercised in development rather than
    // discovered at deploy.
    proxy: {},
  },
  build: {
    outDir: "dist",
    sourcemap: true,
    target: "es2022",
    rollupOptions: {
      output: {
        // Three stable vendor chunks. React and the router change with a
        // dependency bump; motion and the Radix primitives change on their own
        // schedule. Splitting them means an app deploy does not invalidate all
        // of the vendor cache.
        manualChunks: {
          react: ["react", "react-dom", "react-router-dom"],
          motion: ["framer-motion"],
          ui: [
            "@radix-ui/react-dialog",
            "@radix-ui/react-dropdown-menu",
            "@radix-ui/react-scroll-area",
            "@radix-ui/react-separator",
            "@radix-ui/react-slot",
            "@radix-ui/react-tooltip",
            "lucide-react",
          ],
        },
      },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    css: true,
    include: ["src/**/*.{test,spec}.{ts,tsx}"],
  },
});
