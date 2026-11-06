# syntax=docker/dockerfile:1
# 多阶段构建：builder 只装依赖与包，runtime 不含编译工具链；最终以非 root 运行。

FROM python:3.12-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build

COPY pyproject.toml ./
COPY app ./app
RUN pip install --prefix=/install .


FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --create-home app

COPY --from=builder /install /usr/local

WORKDIR /srv
COPY alembic.ini ./
COPY alembic ./alembic
COPY entrypoint.sh /usr/local/bin/entrypoint.sh

RUN chmod +x /usr/local/bin/entrypoint.sh \
    && chown -R app:app /srv

USER app

EXPOSE 8000

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]


# 开发/门禁专用镜像：装齐 dev extras 与测试依赖，供 `make test|lint|format` 使用。
# 不进入运行拓扑（Compose 里挂在 `dev` profile，`up` 不会启动它），也不跑迁移。
FROM python:3.12-slim AS dev

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv

COPY pyproject.toml ./
COPY app ./app
RUN pip install ".[dev]"

COPY alembic.ini ./
COPY alembic ./alembic

CMD ["pytest", "-q"]

