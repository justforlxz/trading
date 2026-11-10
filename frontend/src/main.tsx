import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";

import App from "./App";
import { ThemeProvider } from "./lib/theme";
import "./index.css";

/**
 * 开发态先启动 MSW 假后端，页面因此不需要真实后端即可渲染。
 * 生产构建走同一份契约的真实 FastAPI 进程，`DEV` 为假时完全跳过。
 */
async function bootstrap(): Promise<void> {
  if (import.meta.env.DEV) {
    const { worker } = await import("./mocks/browser");
    await worker.start({ onUnhandledRequest: "bypass" });
  }

  const container = document.getElementById("root");
  if (!container) {
    throw new Error("root element not found");
  }

  createRoot(container).render(
    <StrictMode>
      <ThemeProvider>
        <BrowserRouter>
          <App />
        </BrowserRouter>
      </ThemeProvider>
    </StrictMode>,
  );
}

void bootstrap();
