import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  // 开发服务器把 /api 反代到本机 API 进程；生产由同一个 uvicorn 直接服务静态产物。
  server: {
    port: 5173,
    host: true,
    proxy: {
      "/api": {
        target: process.env.VITE_API_TARGET ?? "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
  preview: { port: 5173, host: true },
});
