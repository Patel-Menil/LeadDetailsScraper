# ========================================================
# Stage 1: Build Next.js Production Standalone Frontend
# ========================================================
FROM node:20-slim AS frontend-builder
WORKDIR /app

# Install dependencies
COPY package*.json ./
RUN npm ci

# Copy configuration and source files
COPY tsconfig.json next.config.js tailwind.config.js postcss.config.js ./
COPY public/ ./public/
COPY src/ ./src/

# Build standalone bundle
RUN npm run build

# ========================================================
# Stage 2: Final Single Application Container
# ========================================================
FROM python:3.11-slim
WORKDIR /app

# Configure resilient APT settings for network timeouts/retries
RUN echo 'Acquire::Retries "5";' > /etc/apt/apt.conf.d/99network.conf && \
    echo 'Acquire::http::Timeout "120";' >> /etc/apt/apt.conf.d/99network.conf && \
    echo 'Acquire::https::Timeout "120";' >> /etc/apt/apt.conf.d/99network.conf

# Install curl for health checks and bash
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Copy Node.js binary from node:20-slim
COPY --from=node:20-slim /usr/local/bin/node /usr/local/bin/node

# Install Python backend dependencies
COPY requirements.txt .
RUN pip install --default-timeout=1000 --retries=10 -r requirements.txt
RUN patchright install --with-deps chromium

# Copy Next.js standalone build artifacts into /app/frontend
COPY --from=frontend-builder /app/.next/standalone ./frontend/
COPY --from=frontend-builder /app/.next/static ./frontend/.next/static
COPY --from=frontend-builder /app/public ./frontend/public

# Copy Python backend application code
COPY src/ ./src/

# Copy process supervisor startup script
COPY start.sh /app/start.sh
RUN tr -d '\r' < /app/start.sh > /app/start_clean.sh && mv /app/start_clean.sh /app/start.sh && chmod +x /app/start.sh

# Prepare persistent data storage directories
RUN mkdir -p /app/data/uploads /app/data/batches

ENV PYTHONUNBUFFERED=1 \
    NODE_ENV=production \
    DATA_DIR=/app/data \
    BACKEND_API_URL=http://127.0.0.1:8000 \
    PORT=3000

# Expose both Next.js frontend (3000) and backend API (8000)
EXPOSE 3000 8000

# Container healthcheck: verify both backend and frontend are responsive
HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
  CMD curl -f http://127.0.0.1:8000/api/health && curl -f http://127.0.0.1:3000/ || exit 1

ENTRYPOINT ["/bin/bash", "/app/start.sh"]
