import { setupWorker } from "msw/browser";

import { handlers } from "./handlers";

/**
 * 浏览器端假后端：仅在 `vite dev` 下启用（见 `src/main.tsx`）。
 * 页面只认 `contracts/openapi.json` 定义的形状，因此可以脱离真实后端开发。
 */
export const worker = setupWorker(...handlers);
