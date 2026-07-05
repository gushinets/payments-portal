# Project Documentation

Проектные документы, архитектурные решения и материалы по MVP находятся в этой
папке, чтобы рабочий корень репозитория оставался под код, конфиги и README.

## Документы

- [architecture.md](architecture.md) - платформенная архитектура для продуктов, подписок,
  платежного и legal-контура.
- [mvp-blueprint.md](mvp-blueprint.md) - расширенный MVP blueprint с региональными контурами,
  account/payment model и будущими backend-сущностями.
- [mvp-user-journey-and-pages.md](mvp-user-journey-and-pages.md) - user journey, структура сайта и требования к
  страницам MVP.
- [payment-portal-data-model.md](payment-portal-data-model.md) - целевая модель
  данных Payment Portal и миграционный план от текущей реализации.
- [deployment-diagram.md](deployment-diagram.md) - региональная схема деплоя и
  routing/data-plane правила.

## Связанные файлы реализации

- Web routes: [apps/web/src/app/ru](../../apps/web/src/app/ru/), checkout UI
  [CheckoutClient.tsx](../../apps/web/src/components/CheckoutClient.tsx), result
  UI [PaymentResultClient.tsx](../../apps/web/src/components/PaymentResultClient.tsx).
- Catalog/legal data: [catalog.ts](../../apps/web/src/lib/catalog.ts),
  [legal.ts](../../apps/web/src/lib/legal.ts), RU legal drafts
  [docs/legal/ru/2026-07-02](../legal/ru/2026-07-02/).
- API: [main.py](../../apps/api/app/main.py),
  [auth.py](../../apps/api/app/auth.py),
  [cloudpayments.py](../../apps/api/app/cloudpayments.py).
- Persistence: [models.py](../../apps/api/app/models.py),
  [database.py](../../apps/api/app/database.py),
  [alembic versions](../../apps/api/alembic/versions/).
