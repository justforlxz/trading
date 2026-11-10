import { defineConfig } from "vitest/config";

// 前端只用 vitest 跑 MSW 假后端的行为断言，不需要 DOM 环境。
export default defineConfig({
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
  },
});
