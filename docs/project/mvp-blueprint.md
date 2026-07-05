# MVP blueprint для запуска 2 продуктов с обработкой ПДн, product-aware entrypoints и RU/Global контурами

## Цель MVP

Минимальный вариант должен позволять запустить два продукта, законно начать обработку персональных данных, привязывать оплату к конкретному пользователю и активировать подписку по webhook. При этом MVP должен учитывать вход по конкретному продукту и разделение на RU и Global версии сайта и платежного/документарного контура.[cite:43][cite:129][cite:134][cite:161]

## MVP scope

### Что входит

- 1 платформа / 1 оператор ПДн.
- 2 региональных контура: `RU` и `Global`.
- 1 веб-контур auth-checkout в двух региональных версиях.
- 2 продукта.
- product-aware entrypoints из extensions.
- 1 модель аккаунта.
- региональные версии документов.
- 1 payment provider на контур или соответствующий набор провайдеров.
- 1 backend с webhook handling.

### Что не обязательно в первой версии

- Отдельные маркетинговые страницы под каждый продукт.
- Сложная CRM.
- Рекуррентные списания.
- Раздельные legal flows под каждый продукт.
- Отдельные product-specific документы, если продукты укладываются в общую платформенную модель.

## MVP-структура сайта

Текущая реализация в репозитории покрывает RU-контур. Global/EN routes ниже
остаются целевой структурой, пока соответствующие файлы не добавлены.

| URL | Назначение | Файл |
|---|---|---|
| `/ru/auth-checkout` | RU-flow: логин, документы, выбор продукта, старт оплаты | [page.tsx](../../apps/web/src/app/ru/auth-checkout/page.tsx), [CheckoutClient.tsx](../../apps/web/src/components/CheckoutClient.tsx) |
| `/ru/privacy` | RU политика обработки персональных данных | [page.tsx](../../apps/web/src/app/ru/privacy/page.tsx), [01-privacy-policy.md](../legal/ru/2026-07-02/01-privacy-policy.md) |
| `/ru/offer` | RU оферта (условия сервиса и автопродления) | [page.tsx](../../apps/web/src/app/ru/offer/page.tsx), [03-offer.md](../legal/ru/2026-07-02/03-offer.md) |
| `/ru/cancellation` | RU условия отмены подписки и возврата средств | [page.tsx](../../apps/web/src/app/ru/cancellation/page.tsx), [04-cancellation-refund.md](../legal/ru/2026-07-02/04-cancellation-refund.md) |
| `/ru/cookies` | RU политика куки | [page.tsx](../../apps/web/src/app/ru/cookies/page.tsx), [05-cookie-policy.md](../legal/ru/2026-07-02/05-cookie-policy.md) |
| `/ru/security` | RU политика информационной безопасности | [page.tsx](../../apps/web/src/app/ru/security/page.tsx), [06-security-policy.md](../legal/ru/2026-07-02/06-security-policy.md) |
| `/ru/consent-personal-data` | RU согласие на обработку персональных данных | [page.tsx](../../apps/web/src/app/ru/consent-personal-data/page.tsx), [02-consent-personal-data.md](../legal/ru/2026-07-02/02-consent-personal-data.md) |
| `/ru/payment-result` | RU экран возврата после оплаты | [page.tsx](../../apps/web/src/app/ru/payment-result/page.tsx), [PaymentResultClient.tsx](../../apps/web/src/components/PaymentResultClient.tsx) |
| `/ru/products` | RU каталог продуктов | [page.tsx](../../apps/web/src/app/ru/products/page.tsx), [ProductCards.tsx](../../apps/web/src/components/ProductCards.tsx) |
| `/en/auth-checkout` | Global-flow: логин, verify email, документы, выбор продукта, старт оплаты | not implemented |
| `/en/privacy` | Global privacy policy | not implemented |
| `/en/offer` | Global terms of service | not implemented |
| `/en/cancellation` | Global cancellation & refund policy | not implemented |
| `/en/cookies` | Global cookie policy | not implemented |
| `/en/security` | Global security policy | not implemented |
| `/en/payment-result` | Global экран возврата после оплаты | not implemented |

## Product-aware entrypoints

### Рекомендуемые URL входа

| Сценарий | Пример |
|---|---|
| Вход из продукта RU | `/ru/auth-checkout?product=ext_a` |
| Вход из второго продукта RU | `/ru/auth-checkout?product=ext_b` |
| Вход из bundle RU | `/ru/auth-checkout?bundle=scenario_1` |
| Вход из продукта Global | `/en/auth-checkout?product=ext_a` |
| Вход из bundle Global | `/en/auth-checkout?bundle=scenario_1` |
| Вход из общего каталога | `/ru/auth-checkout?entry=catalog` или `/en/auth-checkout?entry=catalog` |

### Логика на первом экране

Если пользователь пришел из конкретного extension, первый экран должен сразу показывать именно этот продукт: название, краткое описание, тариф, текущий статус подписки и кнопку оплаты или продления. Это снижает лишний выбор и улучшает конверсию checkout flow.[cite:165][cite:174][cite:177][cite:189]

## Geo-routing logic

### Что учитывать

Первичный региональный контур можно определять по geo/ip и языку браузера, но жесткий редирект без выбора пользователя делать не рекомендуется. Пользователь должен иметь возможность вручную переключить региональный контур.[cite:161][cite:164]

### Рекомендуемая логика

- Пользователь из РФ по умолчанию открывает RU-контур.[cite:161][cite:172]
- Пользователь вне РФ по умолчанию открывает Global-контур.[cite:161]
- На первом экране есть переключатель `RU / Global`.[cite:161][cite:164]
- Выбранный регион сохраняется в сессии и участвует в checkout logic.

## MVP flow-state machine

| State | Условие входа | Действие |
|---|---|---|
| `product-intro` | Есть `product` или `bundle` в URL | Показ информации по конкретному продукту / bundle |
| `login` | Нет активной сессии | Ввод email / magic link / OTP |
| `verify-email` | Email не подтвержден | Подтверждение email через код или ссылку.[cite:91][cite:95][cite:100] |
| `consents` | Нет acceptance актуальных документов текущего контура | Подтверждение документов и согласий.[cite:42][cite:45][cite:97] |
| `account` | Все обязательные проверки пройдены | Показ аккаунта и статусов продуктов |
| `checkout` | Выбран продукт или тариф | Создание заказа и показ summary |
| `pending-payment` | Пользователь ушел в эквайринг или вернулся без webhook | Ожидание подтверждения статуса |
| `active` | Получен успешный webhook | Подписка активна |

## MVP backend blueprint

### Таблицы

| Таблица | Поля | Назначение |
|---|---|---|
| `users` | `id`, `email`, `email_verified_at`, `status`, `created_at` | Аккаунты |
| `document_versions` | `id`, `region`, `doc_type`, `version`, `published_at`, `is_active` | Версии документов по регионам |
| `document_acceptances` | `id`, `user_id`, `temp_session_id`, `region`, `doc_type`, `version`, `accepted_at`, `ip`, `user_agent`, `entrypoint_type`, `entrypoint_value` | Лог принятия документов |
| `products` | `id`, `code`, `name`, `description`, `billing_mode`, `status` | Каталог продуктов |
| `plans` | `id`, `product_id`, `region`, `code`, `period`, `price`, `currency`, `is_bundle`, `status` | Тарифы по продуктам и регионам |
| `orders` | `id`, `user_id`, `region`, `entrypoint_type`, `entrypoint_value`, `product_id`, `plan_id`, `amount`, `currency`, `provider`, `provider_payment_id`, `status`, `created_at` | Заказы |
| `subscriptions` | `id`, `user_id`, `region`, `product_scope`, `product_id`, `bundle_id`, `plan_id`, `status`, `starts_at`, `expires_at`, `source_order_id` | Подписки |
| `payment_configs` | `id`, `region`, `provider`, `currency`, `is_active` | Активные платежные конфиги по контурам |
| `webhook_events` | `id`, `region`, `provider`, `event_type`, `payload_hash`, `received_at`, `processed_at`, `status` | Идемпотентная обработка webhook |

### API endpoints

Целевая таблица ниже описывает production API. Текущие backend routes находятся
в [auth.py](../../apps/api/app/auth.py) и
[cloudpayments.py](../../apps/api/app/cloudpayments.py); app wiring в
[main.py](../../apps/api/app/main.py).

| Endpoint | Метод | Назначение |
|---|---|---|
| `/api/context/resolve` | POST | Определить регион, entrypoint и стартовое состояние flow |
| `/api/auth/request-login` | POST | Отправить magic link / OTP |
| `/api/auth/verify` | POST | Подтвердить email / код |
| `/api/me` | GET | Профиль текущего пользователя |
| `/api/me/products` | GET | Список продуктов и статусов подписки |
| `/api/documents/current` | GET | Актуальные версии документов по региону |
| `/api/documents/accept` | POST | Фиксация принятия документов |
| `/api/checkout/session` | POST | Создание checkout session с учетом региона и entrypoint |
| `/api/checkout/confirm` | POST | Создание order и получение payment URL |
| `/api/payments/webhook/{provider}` | POST | Webhook-приемник |
| `/api/me/subscriptions` | GET | Текущие подписки пользователя |

Текущая RU MVP-реализация:

| Endpoint | Метод | Файл |
|---|---|---|
| `/api/auth/register` | POST | [auth.py](../../apps/api/app/auth.py) |
| `/api/auth/login` | POST | [auth.py](../../apps/api/app/auth.py) |
| `/api/auth/session` | GET | [auth.py](../../apps/api/app/auth.py) |
| `/api/auth/payment-status` | GET | [auth.py](../../apps/api/app/auth.py) |
| `/api/auth/logout` | POST | [auth.py](../../apps/api/app/auth.py) |
| `/api/auth/checkout-intent` | POST | [auth.py](../../apps/api/app/auth.py) |
| `/api/cloudpayments/{check,pay,fail,refund,recurrent}` | POST | [cloudpayments.py](../../apps/api/app/cloudpayments.py) |
| `/health` | GET | [main.py](../../apps/api/app/main.py) |

## MVP payment logic

### Что происходит при оплате

1. Пользователь приходит в региональный контур и видит продукт, из которого пришел.
2. Backend определяет `region`, `entrypoint_type`, `entrypoint_value`, `product_id` и допустимые тарифы.
3. Пользователь выбирает тариф.
4. Backend создает внутренний `order` со статусом `pending`.[cite:58][cite:64]
5. В платежный провайдер передается merchant order id и, если возможно, metadata для связки с пользователем, продуктом, регионом и тарифом.[cite:58][cite:60][cite:64]
6. Пользователь оплачивает на hosted payment page провайдера.[cite:60][cite:64]
7. Провайдер отправляет webhook в backend.[cite:57][cite:58][cite:62]
8. Backend проверяет подпись, сумму, валюту и переводит order в `paid`.[cite:57][cite:58][cite:60]
9. Подписка создается или продлевается в нужном регионе и scope продукта.[cite:55][cite:62]

### Почему нужны `region` и `entrypoint`

`region` нужен для выбора документов, валюты, платежного провайдера и правил checkout flow. `entrypoint` нужен, чтобы первая страница и заказ были привязаны к конкретному продукту или bundle, а не к абстрактному каталогу.[cite:161][cite:164][cite:165][cite:174]

## Что подать и опубликовать для запуска

- Уведомление в Роскомнадзор до старта обработки ПДн.[cite:43][cite:129][cite:134]
- Политику обработки персональных данных для RU-контура.[cite:142][cite:144]
- Оферту для RU-контура (с явным указанием условий автопродления).[cite:137][cite:142]
- Условия отмены подписки и возврата средств для RU-контура.
- Политику куки для RU-контура.
- Политику информационной безопасности для RU-контура (со ссылкой на PCI DSS CloudPayments).
- При необходимости отдельные Global-документы для международного контура.[cite:161][cite:164]
- Внутренние документы по ПДн: назначение ответственного и правила обработки.[cite:133][cite:140][cite:143]

## Минимальный чек-лист запуска

- Уведомление РКН подано.[cite:43][cite:129]
- RU-документы опубликованы: политика ПДн, оферта, условия отмены, политика куки, политика ИБ.[cite:142][cite:144]
- Global-документы подготовлены, если включается международный контур.[cite:161][cite:164]
- Домен и хостинг зарегистрированы на то же юрлицо или ИП, что и договор с CloudPayments.
- Сервер с персональными данными российских граждан физически находится в России (допустимые провайдеры: Reg.ru, Timeweb, Selectel, Yandex Cloud, VK Cloud).
- HTTPS подключён на всём домене.
- Футер с юрданными (наименование, ИНН, ОГРН/ОГРНИП, адрес), email поддержки и логотипами платёжных методов размещён на всех страницах.
- Куки-баннер работает при первом посещении.
- Работает flow: `product-intro -> login -> verify email -> consents -> account -> checkout`.[cite:91][cite:95][cite:42][cite:165]
- На шаге `checkout` при подписке с автопродлением присутствует отдельный незаполненный чекбокс явного согласия на регулярные списания.
- Принятие документов логируется с учётом `region` и версии документа.
- Оплата идёт через hosted payment page.
- Подписка активируется только через webhook.[cite:57][cite:58][cite:60]
- В кабинете видны 2 продукта и их статусы.
- Модель данных допускает bundle и all-access без миграции core-логики.
