FROM node:20-alpine@sha256:fb4cd12c85ee03686f6af5362a0b0d56d50c58a04632e6c0fb8363f609372293

WORKDIR /app

ARG NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
ARG NEXT_PUBLIC_CLOUDPAYMENTS_PUBLIC_ID=
ARG NEXT_PUBLIC_CLOUDPAYMENTS_ENABLED=false

ENV NEXT_PUBLIC_API_BASE_URL=$NEXT_PUBLIC_API_BASE_URL
ENV NEXT_PUBLIC_CLOUDPAYMENTS_PUBLIC_ID=$NEXT_PUBLIC_CLOUDPAYMENTS_PUBLIC_ID
ENV NEXT_PUBLIC_CLOUDPAYMENTS_ENABLED=$NEXT_PUBLIC_CLOUDPAYMENTS_ENABLED

COPY package.json package-lock.json ./
COPY apps/web/package.json ./apps/web/package.json

RUN npm ci

COPY apps/web ./apps/web
COPY docs/legal ./docs/legal

RUN npm run build:web

RUN chown -R node:node /app

USER node

EXPOSE 3000

CMD ["npm", "--workspace", "@anytoolai/web", "run", "start", "--", "--hostname", "0.0.0.0", "--port", "3000"]
