FROM node:22-alpine@sha256:c610fcdfb1d5b4740dd70c284ed3cb16bb857e0f7166196e36a5501df7a3aa32 AS build
WORKDIR /app
ARG PLATEOS_VERSION=development
ENV VITE_PLATEOS_VERSION=$PLATEOS_VERSION
ENV NPM_CONFIG_AUDIT=false NPM_CONFIG_FUND=false
COPY package.json package-lock.json ./
RUN npm ci --ignore-scripts
COPY . .
RUN npm run build

FROM caddy:2-alpine@sha256:5f5c8640aae01df9654968d946d8f1a56c497f1dd5c5cda4cf95ab7c14d58648
RUN setcap -r /usr/bin/caddy \
    && addgroup -g 10001 -S plateos \
    && adduser -u 10001 -S -D -H -G plateos plateos
COPY Caddyfile /etc/caddy/Caddyfile
COPY --chown=plateos:plateos --from=build /app/dist /srv
EXPOSE 8080
USER 10001:10001
