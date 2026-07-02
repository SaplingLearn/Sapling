# syntax=docker/dockerfile:1
# Multi-stage build for the Next.js 16 frontend (#173). next.config.ts sets
# output: "standalone", so the runtime image ships only the minimal traced
# server instead of the full node_modules tree.
#
# Referenced by docker-compose.yml's `frontend` service. node 22 matches CI
# (.github/workflows/ci.yml) and Cloudflare Workers Builds; npm is pinned to the
# engines-required range (>=10.9.0 <11) before any install.

FROM node:22-alpine AS deps
WORKDIR /app
RUN npm install -g npm@10.9.2 --engine-strict=false
COPY package.json package-lock.json ./
RUN npm ci

FROM node:22-alpine AS builder
WORKDIR /app
# NEXT_PUBLIC_* are inlined into the client bundle at build time, so the backend
# URL must be supplied here (compose passes it as the BACKEND_URL build arg).
ARG BACKEND_URL
ENV NEXT_PUBLIC_API_URL=${BACKEND_URL}
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm install -g npm@10.9.2 --engine-strict=false
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM node:22-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
ENV PORT=3000
ENV NEXT_TELEMETRY_DISABLED=1
RUN addgroup -g 1001 -S nodejs && adduser -S nextjs -u 1001
# Standalone output: server.js + a pruned node_modules, plus static assets.
COPY --from=builder /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static
USER nextjs
EXPOSE 3000
CMD ["node", "server.js"]
