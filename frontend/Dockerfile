# syntax=docker/dockerfile:1

FROM node:22-alpine AS build
WORKDIR /app
RUN corepack enable
COPY package.json pnpm-lock.yaml ./
RUN --mount=type=cache,target=/root/.local/share/pnpm/store pnpm install --frozen-lockfile
COPY . .
ARG VITE_API_URL=""
ARG VITE_ENABLE_DEV_TOOLS="false"
ENV VITE_API_URL=$VITE_API_URL \
    VITE_ENABLE_DEV_TOOLS=$VITE_ENABLE_DEV_TOOLS \
    VITE_USE_MOCKS=false
RUN pnpm build

FROM nginx:1.27-alpine AS runtime
ENV API_UPSTREAM=http://gateway:8000
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
HEALTHCHECK --interval=30s --timeout=3s CMD wget -qO- http://127.0.0.1/healthz || exit 1
