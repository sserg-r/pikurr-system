# Этап 1: сборка
FROM node:20-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

# Этап 2: раздача через nginx
FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
# index.html не кэшируется; хэшированные ассеты — вечный кэш
RUN printf 'server {\n  listen 80;\n  root /usr/share/nginx/html;\n  index index.html;\n  location / {\n    try_files $uri $uri/ /index.html;\n    add_header Cache-Control "no-cache, must-revalidate";\n  }\n  location /assets/ {\n    expires 1y;\n    add_header Cache-Control "public, immutable";\n  }\n}\n' > /etc/nginx/conf.d/default.conf
