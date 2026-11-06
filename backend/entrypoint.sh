#!/bin/sh
# 统一 entrypoint：只有 api 容器执行迁移（overview §5 的启动顺序），
# `alembic upgrade head` 本身幂等，重复启动不产生副作用。
set -eu

if [ "${RUN_MIGRATIONS:-0}" = "1" ]; then
  echo "entrypoint: running alembic upgrade head"
  alembic upgrade head
fi

exec "$@"
