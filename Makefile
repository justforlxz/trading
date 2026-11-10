SHELL := /bin/bash
# 解释器路径相对仓库根解析，因此在 backend/ 下执行时可用绝对路径（也可覆盖：make test PY=...）
PY ?= .venv/bin/python
PYTHON := $(abspath $(PY))
BACKEND := backend

# 本地 PostgreSQL：容器名与连接参数固定，与 `.env.example` 里的 DATABASE_URL 一致。
DB_CONTAINER ?= trading-db
DB_IMAGE ?= docker.io/library/postgres:16-alpine
DB_PORT ?= 5432
DB_NAME ?= trading
DB_USER ?= trading
DB_PASSWORD ?= trading

.DEFAULT_GOAL := help

.PHONY: help install test lint format verify-live db-up db-down migrate

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

# 本地数据库只用一个 podman 容器，不做编排：容器已存在就只启动，数据留在容器里。
# 就绪判定必须走 TCP（`-h 127.0.0.1`）：初始化期间临时起的 postgres 只监听 unix
# socket，用 socket 探测会在初始化中途就报就绪，随后服务重启，第一条 SQL 直接失败。
db-up: ## 启动本地 PostgreSQL（podman run；容器已存在则直接启动）
	@set -e; \
	if [ ! -f .env ]; then cp .env.example .env; echo "db-up: 已按 .env.example 生成 .env"; fi; \
	if podman container exists $(DB_CONTAINER); then \
	  podman start $(DB_CONTAINER) >/dev/null; \
	else \
	  podman run -d --name $(DB_CONTAINER) \
	    -e POSTGRES_USER=$(DB_USER) \
	    -e POSTGRES_PASSWORD=$(DB_PASSWORD) \
	    -e POSTGRES_DB=$(DB_NAME) \
	    -p 127.0.0.1:$(DB_PORT):5432 \
	    $(DB_IMAGE) >/dev/null; \
	fi; \
	for _ in $$(seq 1 60); do \
	  if podman exec $(DB_CONTAINER) pg_isready -h 127.0.0.1 -U $(DB_USER) -d $(DB_NAME) >/dev/null 2>&1; then \
	    echo "db-up: PostgreSQL 就绪 127.0.0.1:$(DB_PORT)/$(DB_NAME)"; exit 0; \
	  fi; \
	  sleep 0.5; \
	done; \
	echo "db-up: PostgreSQL 在 30s 内未就绪" >&2; exit 1

db-down: ## 停止本地 PostgreSQL 容器（数据保留在容器内）
	@if podman container exists $(DB_CONTAINER); then podman stop -t 5 $(DB_CONTAINER) >/dev/null; \
	  echo "db-down: $(DB_CONTAINER) 已停止"; else echo "db-down: $(DB_CONTAINER) 不存在"; fi

migrate: ## 把数据库结构推进到最新版本（等价于 alembic upgrade head）
	cd $(BACKEND) && $(PYTHON) -m alembic upgrade head

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
