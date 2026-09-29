import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import { viteSingleFile } from "vite-plugin-singlefile";

// Two builds from the same code:
//   npm run build        dist/: the pages the Python server sends, reading /api/snapshot
//   npm run build:demo   dist-demo/index.html: one self-contained file with made-up leads
//                        (src/demo/snapshot.json), to look at the pages with no server at all
export default defineConfig(({ mode }) => {
  const demo = mode === "demo";
  return {
    plugins: demo ? [react(), viteSingleFile()] : [react()],
    base: demo ? "./" : "/",
    build: {
      outDir: demo ? "dist-demo" : "dist",
      emptyOutDir: true,
    },
  };
});
