# The evaluation application's UI: a static bundle Fred shows at /apps/evaluation/.
FROM mirror.gcr.io/node:22.13.0-slim AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --ignore-scripts --no-audit --no-fund
COPY index.html tsconfig.json vite.config.ts ./
COPY scripts/check-toolchain.mjs ./scripts/check-toolchain.mjs
COPY src ./src
RUN npm run build

FROM mirror.gcr.io/nginxinc/nginx-unprivileged:1.27.3-alpine
COPY nginx/default.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist/ /usr/share/nginx/html/apps/evaluation/
# config.json ({"hostOrigin": ...}) is mounted at run time, never baked in:
# the same image serves any Fred origin.
EXPOSE 8080
