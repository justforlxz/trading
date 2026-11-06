# syntax=docker/dockerfile:1
# 构建阶段装依赖并产出静态资源；运行阶段只用 nginx，不带 node 与源码。

FROM node:22-alpine AS builder

ENV PNPM_HOME=/pnpm \
    PATH=/pnpm:$PATH
RUN npm install -g pnpm@9.15.9

WORKDIR /app

COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

COPY . .
RUN pnpm build


FROM nginx:1.27-alpine AS runtime

RUN rm -f /etc/nginx/conf.d/default.conf
COPY nginx.conf /etc/nginx/conf.d/trading.conf
COPY --from=builder /app/dist /usr/share/nginx/html

EXPOSE 80
