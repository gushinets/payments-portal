# AnytoolAI Payments Portal RU MVP

Первая RU-версия сайта для предъявления CloudPayments и подготовки платежного
контура. Источник решений: `docs/project/tz-cloudpayments-ru-mvp.md`.

## Документация

Проектные документы и архитектурные материалы перенесены в `docs/project`:

- `docs/project/tz-cloudpayments-ru-mvp.md`
- `docs/project/architecture.md`
- `docs/project/mvp-blueprint.md`
- `docs/project/mvp-user-journey-and-pages.md`

Дизайн-система находится в `docs/design-system/bundle3`.

## Что входит

- Next.js сайт в `apps/web`.
- FastAPI backend в `apps/api`.
- RU routes: `/ru`, `/ru/products`, `/ru/auth-checkout`, `/ru/payment-result`,
  `/ru/privacy`, `/ru/offer`, `/ru/cancellation`, `/ru/cookies`, `/ru/security`.
- Demo magic link flow без реальной отправки email.
- Demo payment flow: кнопка оплаты ведет на `/ru/payment-result?status=demo`.
- CloudPayments webhook endpoints:
  - `POST /api/cloudpayments/check`
  - `POST /api/cloudpayments/pay`
  - `POST /api/cloudpayments/fail`
  - `POST /api/cloudpayments/refund`
  - `POST /api/cloudpayments/recurrent`
- PostgreSQL только для таблицы `payment_webhook_events`.
- Alembic migration для технического журнала webhook-событий.

## Дизайн-система

UI использует Bundle 3 из архива:

```text
D:\Work\AI\Design system\files_Bandl_3.zip
```

Web-релевантные файлы дизайн-системы сохранены в репозитории:

- `docs/design-system/bundle3/SKILL.md`
- `docs/design-system/bundle3/PROMPT_SNIPPET.md`
- `docs/design-system/bundle3/web.md`

В код перенесены необходимые tokens и web rules: dark premium AI-native,
glass surfaces, bento grids, indigo gradient accents, teal highlights,
DM Sans / DM Mono / Cabinet Grotesk font stack. Файлы `extension.md` и
`mobile.md` из исходного архива не добавлены, потому что текущий проект
реализует только web-портал.

## Локальный запуск

1. Скопировать env template:

```bash
cp .env.example .env
```

2. Поднять PostgreSQL:

```bash
docker compose up -d
```

3. Установить backend dependencies:

```bash
python -m venv .venv
. .venv/Scripts/activate
pip install -r apps/api/requirements-dev.txt
```

4. Применить миграции:

```bash
python -m alembic -c apps/api/alembic.ini upgrade head
```

5. Запустить API:

```bash
python -m uvicorn app.main:app --reload --app-dir apps/api
```

API будет доступен на `http://localhost:8000`.

6. Установить frontend dependencies и запустить сайт:

```bash
npm install
npm run dev:web
```

Web будет доступен на `http://localhost:3000`.

Для production preview после сборки:

```bash
npm run build:web
npm run start:web
```

## Проверки

```bash
npm run lint:web
npm run build:web
pytest apps/api/tests
```

Для проверки webhook-сохранения с PostgreSQL:

```bash
curl -X POST http://localhost:8000/api/cloudpayments/pay \
  -H "Content-Type: application/json" \
  -d "{\"InvoiceId\":\"demo-1\",\"TransactionId\":\"tx-1\",\"AccountId\":\"user@example.com\",\"Amount\":\"990.00\",\"Currency\":\"RUB\"}"
```

## CloudPayments configuration

По умолчанию платежи выключены:

```text
CLOUDPAYMENTS_PUBLIC_ID=
CLOUDPAYMENTS_API_SECRET=
CLOUDPAYMENTS_ENABLED=false
NEXT_PUBLIC_CLOUDPAYMENTS_PUBLIC_ID=
NEXT_PUBLIC_CLOUDPAYMENTS_ENABLED=false
```

Если `CLOUDPAYMENTS_API_SECRET` пустой, webhook signature check работает в
demo-mode и не блокирует запросы. Если secret задан, backend ожидает HMAC в
`Content-HMAC` или `X-Content-HMAC`.

Для frontend-виджета после получения terminal id используются публичные env:

```text
NEXT_PUBLIC_CLOUDPAYMENTS_PUBLIC_ID=pk_xxx
NEXT_PUBLIC_CLOUDPAYMENTS_ENABLED=true
```

Пока эти значения не заданы, кнопка оплаты работает как заглушка и ведет на
`/ru/payment-result?status=demo`.

## Важные ограничения v1

- Только RU-контур.
- Нет полноценного личного кабинета.
- Нет полной модели пользователей, продуктов, тарифов, заказов и подписок в БД.
- Нет реальной email-отправки.
- Нет реальной активации подписки.
- Карточные данные не собираются и не хранятся на сайте.
- Юридические тексты являются черновыми и должны быть проверены юристом перед
  реальным запуском.
