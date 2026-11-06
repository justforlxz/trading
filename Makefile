SHELL := /bin/bash
COMPOSE ?= docker compose

# 门禁命令走 dev 镜像：含 dev extras（pytest/ruff），挂载工作区源码，
# 且不跑 entrypoint 迁移（不依赖 postgres）。api-dev 只在 dev profile 下存在。
DEV_COMPOSE = $(COMPOSE) --profile dev
DEV_RUN = $(DEV_COMPOSE) run --rm --no-deps --build api-dev

.DEFAULT_GOAL := help

.PHONY: help up down logs test lint format migrate

help: ## 列出可用目标
	@grep -hE '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "}; {printf "  \033[36m%-8s\033[0m %s\n", $$1, $$2}'

up: ## 构建并启动六个服务，等待健康检查通过
	$(COMPOSE) up -d --build --wait

down: ## 停止并移除容器（保留命名卷）
	$(COMPOSE) down

logs: ## 跟踪全部服务日志
	$(COMPOSE) logs -f --tail=100

test: ## 后端 pytest（容器内）+ 前端构建（宿主机 pnpm）
	$(DEV_RUN) pytest -q
	pnpm --dir frontend build

lint: ## 后端 ruff（容器内）+ 前端 eslint（宿主机 pnpm）
	$(DEV_RUN) ruff check .
	$(DEV_RUN) ruff format --check .
	pnpm --dir frontend lint

format: ## 后端 ruff 自动格式化（改动直接写回工作区）
	$(DEV_RUN) ruff format .

migrate: ## 对运行中的数据库执行 alembic upgrade head（幂等）
	$(COMPOSE) run --rm -e RUN_MIGRATIONS=0 api alembic upgrade head
