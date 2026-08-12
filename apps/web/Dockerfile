FROM node:24.18.0-alpine3.24@sha256:a0b9bf06e4e6193cf7a0f58816cc935ff8c2a908f81e6f1a95432d679c54fbfd

WORKDIR /app

ARG NEXT_PUBLIC_API_BASE_URL=http://localhost:8000

ENV NEXT_PUBLIC_API_BASE_URL=$NEXT_PUBLIC_API_BASE_URL

COPY package.json package-lock.json ./
COPY apps/web/package.json ./apps/web/package.json

RUN npm ci

COPY apps/web ./apps/web
COPY docs/legal ./docs/legal

RUN npm run build:web

USER node

EXPOSE 3000

CMD ["npm", "--workspace", "@anytoolai/web", "run", "start", "--", "--hostname", "0.0.0.0", "--port", "3000"]
