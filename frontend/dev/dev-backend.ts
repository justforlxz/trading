/**
 * 开发态后端替身。
 *
 * 只在 `pnpm dev` 下由 `src/main.tsx` 动态加载：用契约示例返回与真实接口
 * 同形状的响应，使页面无需真实 FastAPI 进程即可渲染。生产构建中该模块
 * 随 `import.meta.env.DEV` 分支一起被剔除，业务代码不感知它的存在。
 */

import { worker } from "../src/mocks/browser";

export async function enableDevBackend(): Promise<void> {
  await worker.start({ onUnhandledRequest: "bypass" });
}
