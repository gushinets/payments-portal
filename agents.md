# Agents Guide

Short repo map for OpenAI-style coding agents. Keep this file concise; put task details in the current prompt or in the relevant docs.

## Priority

1. Current user prompt.
2. This file and any narrower `agents.md`/`AGENTS.md` inside a subtree.
3. [README.md](README.md) for setup, scope, and verification commands.
4. [docs/project/tz-cloudpayments-ru-mvp.md](docs/project/tz-cloudpayments-ru-mvp.md) as the first source of product decisions for the RU MVP.
5. Other project docs only when they match the change area.

## Repository Map

- [apps/web](apps/web/) - Next.js RU payment portal. App routes live in [apps/web/src/app](apps/web/src/app/), shared UI in [apps/web/src/components](apps/web/src/components/), catalog/legal data in [apps/web/src/lib](apps/web/src/lib/), global styles in [apps/web/src/app/globals.css](apps/web/src/app/globals.css).
- [apps/api](apps/api/) - FastAPI backend. Main app is [apps/api/app/main.py](apps/api/app/main.py), auth demo flow is [apps/api/app/auth.py](apps/api/app/auth.py), CloudPayments webhooks are in [apps/api/app/cloudpayments.py](apps/api/app/cloudpayments.py), DB models/session are in [apps/api/app/models.py](apps/api/app/models.py) and [apps/api/app/database.py](apps/api/app/database.py).
- [apps/api/alembic](apps/api/alembic/) - migrations for PostgreSQL webhook storage.
- [apps/api/tests](apps/api/tests/) - backend tests.
- [docs/project](docs/project/) - requirements and architecture. Start with [docs/project/README.md](docs/project/README.md).
- [docs/design-system/bundle3](docs/design-system/bundle3/) - Bundle 3 web design rules. Use [docs/design-system/bundle3/web.md](docs/design-system/bundle3/web.md) for UI work.
- [docker-compose.yml](docker-compose.yml) - local PostgreSQL service.
- [.env.example](.env.example) - environment variable template.

## Change Guidelines

- Keep v1 scoped to the RU CloudPayments MVP unless the user explicitly asks for Global/multi-region work.
- Treat payment activation as webhook-driven, not return-url-driven.
- Do not collect or store card data in this app.
- Legal pages are draft content; avoid presenting them as legally approved.
- For frontend changes, preserve the existing Bundle 3 dark/glass/bento visual language.
- For backend changes, keep FastAPI routes under `/api/...` and add tests when behavior changes.
- Keep generated/build/dependency artifacts out of hand edits.

## Useful Commands

```bash
npm run dev:web
npm run lint:web
npm run build:web
npm run dev:api
npm run test:api
python -m alembic -c apps/api/alembic.ini upgrade head
```

Run the smallest relevant checks before handing work back. For cross-stack changes, prefer `npm run lint:web`, `npm run build:web`, and `npm run test:api`.
