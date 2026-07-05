# Deployment diagram: AnytoolAI Platform + Billing Portal

## Рекомендуемая схема

Платформа и биллинг остаются единым продуктовым решением, но деплоятся по региональным контурам. Общий `Global Control Plane` не хранит ПДн и управляет только конфигурациями, продуктами, workflow, prompts, pricing templates и country matrix. Все пользовательские данные, artifacts, платежи, согласия, события и LLM-вызовы обрабатываются внутри соответствующего `Regional Data Plane`.

В этом репозитории сейчас реализован только RU Billing Portal MVP:
[apps/web](../../apps/web/), [apps/api](../../apps/api/),
[docker-compose.yml](../../docker-compose.yml), [docker-compose.prod.yml](../../docker-compose.prod.yml).
RU web/API entrypoints: [apps/web/src/app/ru](../../apps/web/src/app/ru/),
[auth.py](../../apps/api/app/auth.py), [cloudpayments.py](../../apps/api/app/cloudpayments.py).

```mermaid
flowchart TB
  User["User / Chrome Extension / Web"]
  Edge["Edge Router + Region Resolver<br/>IP country, route region, language,<br/>declared country, account region"]

  Control["Global Control Plane<br/>No personal data<br/><br/>products<br/>workflow definitions<br/>action definitions<br/>prompt templates<br/>pricing templates<br/>country_region_matrix<br/>provider policies"]

  User --> Edge
  Edge -. "load public config / country matrix" .-> Control

  Edge -->|"RU detected or selected"| RU
  Edge -->|"EU detected or selected<br/>Spain / Germany / Italy"| EU

  subgraph RU["RU Data Plane"]
    RU_Web["RU Web / Billing Portal<br/>/ru/auth-checkout<br/>legal pages<br/>payment result"]
    RU_Id["RU Identity + Entitlements"]
    RU_Platform["RU Platform API + Worker<br/>scenario sessions<br/>jobs<br/>artifacts<br/>events"]
    RU_Billing["RU Billing API<br/>orders<br/>manual renewals<br/>webhooks<br/>subscriptions"]
    RU_DB[("RU PostgreSQL<br/>users<br/>consents<br/>orders<br/>subscriptions<br/>scenario_sessions<br/>artifacts<br/>event_log")]
    RU_Obj[("RU Object Storage<br/>documents / larger artifacts")]
    RU_Pay["CloudPayments / YooKassa / Local acquiring"]
    RU_LLM["RU Provider Gateway<br/>local LLM or redacted external LLM<br/>policy controlled"]

    RU_Web --> RU_Id
    RU_Web --> RU_Billing
    RU_Web --> RU_Platform
    RU_Id --> RU_DB
    RU_Billing --> RU_DB
    RU_Platform --> RU_DB
    RU_Platform --> RU_Obj
    RU_Billing --> RU_Pay
    RU_Pay -->|"webhook"| RU_Billing
    RU_Platform --> RU_LLM
  end

  subgraph EU["EU Data Plane"]
    EU_Web["EU Web / Billing Portal<br/>/eu/auth-checkout<br/>GDPR documents<br/>payment result"]
    EU_Id["EU Identity + Entitlements"]
    EU_Platform["EU Platform API + Worker<br/>scenario sessions<br/>jobs<br/>artifacts<br/>events"]
    EU_Billing["EU Billing API<br/>orders<br/>manual renewals<br/>webhooks<br/>subscriptions"]
    EU_DB[("EU PostgreSQL<br/>users<br/>consents<br/>orders<br/>subscriptions<br/>scenario_sessions<br/>artifacts<br/>event_log")]
    EU_Obj[("EU Object Storage")]
    EU_Pay["Stripe / Paddle / Local EU acquiring"]
    EU_LLM["EU Provider Gateway<br/>OpenAI / other providers<br/>DPA + transfer policy"]

    EU_Web --> EU_Id
    EU_Web --> EU_Billing
    EU_Web --> EU_Platform
    EU_Id --> EU_DB
    EU_Billing --> EU_DB
    EU_Platform --> EU_DB
    EU_Platform --> EU_Obj
    EU_Billing --> EU_Pay
    EU_Pay -->|"webhook"| EU_Billing
    EU_Platform --> EU_LLM
  end

  Control -. "signed versioned configs<br/>no user data" .-> RU_Platform
  Control -. "signed versioned configs<br/>no user data" .-> EU_Platform

  RU_Id <-->|"optional account linking token<br/>no raw PII replication"| EU_Id
```

## Логика выбора контура

```mermaid
flowchart TD
  Start["User opens product-aware URL<br/>/ru/auth-checkout?product=...<br/>/eu/auth-checkout?product=..."]
  Resolve["Region Resolver"]
  Signals["Collect signals<br/>route_region<br/>ip_country<br/>browser_language<br/>declared_country<br/>account_region<br/>billing_country later"]
  Matrix["country_region_matrix"]
  Match{"Route region matches<br/>resolved data plane?"}
  Strict{"Strict residency mismatch?<br/>Example: RU user on EU route<br/>or EU user on RU route"}
  Continue["Continue in selected regional flow"]
  Warn["Show region mismatch notice<br/>before collecting email"]
  Switch["Redirect to correct regional data plane<br/>preserve product/bundle entrypoint<br/>do not transfer raw PII"]
  Override{"Override allowed<br/>for this country pair?"}
  Manual["User confirms declared country<br/>log decision"]
  Block["Block checkout or send to support<br/>if legal/payment policy requires"]
  Login["Login / email verification / consents"]
  Checkout["Create order in regional billing"]
  Payment["Hosted payment page"]
  Webhook["Payment webhook"]
  BillingMismatch{"billing_country matches<br/>order region policy?"}
  Active["Activate entitlement / subscription"]
  Review["order.status = region_mismatch<br/>refund / retry checkout / support"]

  Start --> Resolve
  Resolve --> Signals
  Signals --> Matrix
  Matrix --> Match
  Match -->|"yes"| Continue
  Match -->|"no"| Warn
  Warn --> Strict
  Strict -->|"yes"| Switch
  Strict -->|"no"| Override
  Override -->|"yes"| Manual
  Override -->|"no"| Block
  Manual --> Continue
  Switch --> Continue
  Continue --> Login
  Login --> Checkout
  Checkout --> Payment
  Payment --> Webhook
  Webhook --> BillingMismatch
  BillingMismatch -->|"yes"| Active
  BillingMismatch -->|"no"| Review
```

## Ключевые правила

- `Global Control Plane` не хранит пользователей, email, artifacts, переписки, документы, платежи, consent logs или event logs.
- В каждом региональном контуре вместе деплоятся `platform runtime`, `billing`, `identity`, `entitlements`, региональная БД и object storage.
- `Billing Portal` и `Platform Runtime` остаются разными bounded contexts, но используют один региональный `identity/entitlements` слой.
- `Provider Gateway` вызывается только из регионального data plane и применяет региональную LLM-политику.
- Для России контур должен быть самым строгим: отдельный data plane, отдельные документы, отдельные платежные провайдеры, осторожная политика по внешним LLM.
- Для Испании, Германии и Италии достаточно одного EU data plane.
- США, Канада и другие рынки не входят в эту версию диаграммы. Их можно добавить позже как новые `Regional Data Plane` без изменения базовой модели.
- Если пользователь пришел в неправильный регион, нельзя молча собирать ПДн и потом решать проблему. Сначала выбирается корректный региональный контур, потом идет login/checkout.
