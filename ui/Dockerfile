# =============================================================================
# Stage 1: Dependencies
# =============================================================================
# Installs npm dependencies separately from source code.
# Only rebuilds when package.json or package-lock.json change.
FROM node:20-slim AS deps

WORKDIR /app

# Copy only dependency-related files first
COPY package.json package-lock.json ./

# Use npm ci for reproducible builds
RUN npm ci --ignore-scripts

# =============================================================================
# Stage 2: Builder
# =============================================================================
# Builds the production bundle.
# Rebuilds when source code changes, but reuses cached dependencies.
FROM node:20-slim AS builder

WORKDIR /app

# Copy dependencies from deps stage
COPY --from=deps /app/node_modules ./node_modules

# Copy configuration files needed for build
COPY package.json package-lock.json ./
COPY tsconfig.json ./
COPY craco.config.js ./
COPY .prettierrc ./

# Copy i18n files (needed for message extraction)
COPY i18n ./i18n

# Copy source code and public assets
COPY public ./public
COPY src ./src

# Set build-time environment variables
ENV REACT_APP_API_ENDPOINT=/api/2/
ENV NODE_ENV=production
ENV GENERATE_SOURCEMAP=false

# Run any postinstall scripts that were skipped, then build
RUN npm rebuild && \
    npm run messages && \
    npm run build

# =============================================================================
# Stage 3: Production
# =============================================================================
# Minimal nginx image serving only the static build artifacts.
FROM nginx:alpine AS production

LABEL org.opencontainers.image.source="https://github.com/openaleph/openaleph"
LABEL org.opencontainers.image.description="Aleph UI"

# Copy nginx configuration
COPY nginx.conf /etc/nginx/nginx.conf

# Copy only the build output from builder stage
COPY --from=builder /app/build /assets

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD wget -q --spider http://localhost:8080/ || exit 1

EXPOSE 8080

CMD ["nginx", "-g", "daemon off;"]
