FROM node:22-bookworm-slim
WORKDIR /app

COPY frontend/package.json frontend/package-lock.json* ./
RUN mkdir -p /app/node_modules

EXPOSE 5173
CMD ["sh", "-c", "npm install && npm run dev -- --host 0.0.0.0 --port 5173"]
