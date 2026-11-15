import { rm } from "node:fs/promises";
import { resolve } from "node:path";

import react from "@vitejs/plugin-react";
import { defineConfig, type Plugin } from "vite";

const apiProxy = {
  "/api": {
    target: process.env.VITE_API_TARGET ?? "http://localhost:8000",
    changeOrigin: true,
    ws: true,
  },
};

/** MSW 的 service worker 只服务 `vite dev`，生产构建不发布。 */
function excludeMswWorker(): Plugin {
  let outDir = "";
  return {
    name: "exclude-msw-worker-from-build",
    apply: "build",
    configResolved(config) {
      outDir = resolve(config.root, config.build.outDir);
    },
    async closeBundle() {
      await rm(resolve(outDir, "mockServiceWorker.js"), { force: true });
    },
  };
}

export default defineConfig({
  plugins: [react(), excludeMswWorker()],
  // 开发与本地预览都把 /api 反代到本机 API 进程；生产由同一个 uvicorn 直接服务静态产物。
  server: {
    port: 5173,
    host: true,
    proxy: apiProxy,
  },
  preview: { port: 5173, host: true, proxy: apiProxy },
});
