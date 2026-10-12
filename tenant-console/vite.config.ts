import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// dist/: the pages outreach/tenant_console.py serves (see deploy/deploy_tenant_console.sh).
export default defineConfig({
  plugins: [react()],
  base: "/",
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
});
