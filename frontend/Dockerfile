# syntax=docker/dockerfile:1
# Multi-stage build for the Next.js 16 frontend (#173). next.config.ts sets
# output: "standalone", so the runtime image ships only the minimal traced
# server instead of the full node_modules tree.
#
# Referenced by docker-compose.yml's `frontend` service. node 22 matches CI
# (.github/workflows/ci.yml) and Cloudflare Workers Builds; npm is pinned to the
# engines-required range (>=10.9.0 <11) before any install.
#
# -slim (Debian/glibc), NOT -alpine (musl): next.config.ts calls
# initOpenNextCloudflareForDev() at module load, which spawns
# @cloudflare/workerd-linux-64. That binary is dynamically linked against glibc,
# so on Alpine execve fails with a confusing ENOENT (the 124MB file is present;
# its ELF interpreter /lib/ld-linux-x86-64.so.2 is not) and `next build` dies.
# Cloudflare does not ship a musl workerd. CI runs this build on ubuntu-latest,
# which is glibc — so -slim is what actually matches CI.

FROM node:22-slim AS deps
WORKDIR /app
RUN npm install -g npm@10.9.2 --engine-strict=false
COPY package.json package-lock.json ./
RUN npm ci

FROM node:22-slim AS builder
WORKDIR /app
# Two DISTINCT backend origins, because the browser and the Next server reach
# the backend at different addresses under compose:
#
#   BACKEND_URL         server-side origin. next.config.ts bakes it into the
#                       /api/* rewrite destination, and middleware.ts uses it
#                       for its /api/auth/me check. Resolved on the compose
#                       network => http://backend:5000.
#   NEXT_PUBLIC_API_URL inlined into the CLIENT bundle, so it must be an origin
#                       the BROWSER can resolve. The browser runs on the host,
#                       not on the compose network, so it must be the published
#                       port => http://localhost:5000 (compose maps 5000:5000).
#
# These are one and the same public origin in prod/staging (frontend/wrangler.toml);
# they only diverge here. Setting NEXT_PUBLIC_API_URL=${BACKEND_URL} bakes the
# internal hostname "backend" into the client bundle, which the host browser
# cannot resolve -> sign-in (SignInModal) and the newsletter form both fail
# with a DNS error.
#
# Defaults target compose (the only consumer of this image; prod/staging deploy
# to Cloudflare Workers via wrangler, not from here).
ARG BACKEND_URL=http://backend:5000
ARG NEXT_PUBLIC_API_URL=http://localhost:5000
ENV BACKEND_URL=${BACKEND_URL}
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL}
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm install -g npm@10.9.2 --engine-strict=false
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM node:22-slim AS runner
WORKDIR /app
ENV NODE_ENV=production
ENV PORT=3000
ENV NEXT_TELEMETRY_DISABLED=1
# Debian useradd/groupadd (the -slim base); the Alpine busybox
# addgroup/adduser flags used previously do not exist here.
RUN groupadd --gid 1001 nodejs \
    && useradd --uid 1001 --gid nodejs --create-home --shell /bin/bash nextjs
# Standalone output: server.js + a pruned node_modules, plus static assets.
COPY --from=builder /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static
USER nextjs
EXPOSE 3000
CMD ["node", "server.js"]
