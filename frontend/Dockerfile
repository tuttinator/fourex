# Production image for the Railway ``frontend`` service.
#
# Uses Next.js's standalone output so the runtime image contains only the
# files the server actually needs (no ``node_modules/`` duplication).

FROM node:24-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

FROM node:24-alpine AS builder
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
# NEXT_PUBLIC_* vars are inlined into the client bundle at build time,
# so Railway's service variables must be passed through as ARG+ENV here.
ARG NEXT_PUBLIC_API_URL
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM node:24-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

# Non-root user — Next.js doesn't need root in production.
RUN addgroup --system --gid 1001 nodejs \
    && adduser --system --uid 1001 nextjs

# Standalone output includes the server, minimal node_modules, and the
# package.json stub Next.js needs to boot. ``static`` and ``public`` are
# copied separately because ``output: "standalone"`` intentionally does
# not bundle them.
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static
COPY --from=builder --chown=nextjs:nodejs /app/public ./public

USER nextjs

EXPOSE 3000

CMD ["node", "server.js"]
