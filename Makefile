SHELL := /bin/bash
# 解释器路径相对仓库根解析，因此在 backend/ 下执行时可用绝对路径（也可覆盖：make test PY=...）
PY ?= .venv/bin/python
PYTHON := $(abspath $(PY))
BACKEND := backend

.DEFAULT_GOAL := help

.PHONY: help install test lint format verify-live

help: ## 列出可用目标
	@grep -hE '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

install: ## 建本地 venv 并安装后端（可编辑）与前端依赖
	python3 -m venv .venv
	.venv/bin/pip install -e "$(BACKEND)[dev]"
	pnpm --dir frontend install

test: ## 后端 pytest + 前端构建（tsc --noEmit && vite build）
	cd $(BACKEND) && $(PYTHON) -m pytest -q
	pnpm --dir frontend build

lint: ## 后端 ruff check/format --check + 前端 eslint
	cd $(BACKEND) && $(PYTHON) -m ruff check .
	cd $(BACKEND) && $(PYTHON) -m ruff format --check .
	pnpm --dir frontend lint

format: ## 后端 ruff 自动格式化（改动直接写回工作区）
	cd $(BACKEND) && $(PYTHON) -m ruff format .

# 真实进程探活：起一个 uvicorn，打一次 /api/health 后退出。
# 与单测的区别是不用 TestClient，验证「uvicorn app.main:app」这条真实启动路径。
# 用 `( cd ... && exec ... )` 让 $$! 直接是被拉起的 uvicorn 本身（否则拿到的是子 shell，
# trap 杀不到 uvicorn，会留下孤儿进程占住端口，让后续探活命中旧进程而假通过）；
# 日志重定向到文件，避免后台进程继承 stdout 让调用方的管道无法 EOF。
verify-live: ## 起真实 uvicorn 进程并请求 /api/health（含端口占用快速失败）
	@set -e; \
	port=$${PORT:-8010}; \
	log="$${HOME}/.cache/trading/verify-live.log"; \
	mkdir -p "$$(dirname "$$log")"; \
	( cd $(BACKEND) && exec $(PYTHON) -m uvicorn app.main:app --host 127.0.0.1 --port $$port --log-level warning ) >"$$log" 2>&1 & \
	pid=$$!; \
	trap 'kill $$pid 2>/dev/null; wait $$pid 2>/dev/null || true' EXIT INT TERM; \
	for _ in $$(seq 1 60); do \
	  kill -0 $$pid 2>/dev/null || { echo "verify-live: uvicorn 启动即退出（端口 $$port 可能被占用），日志 $$log：" >&2; cat "$$log" >&2; exit 1; }; \
	  if curl -fsS "http://127.0.0.1:$$port/api/health"; then echo; exit 0; fi; \
	  sleep 0.25; \
	done; \
	echo "verify-live: /api/health 在 15s 内未就绪，日志 $$log：" >&2; cat "$$log" >&2; exit 1
