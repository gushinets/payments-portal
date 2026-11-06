# Перенос ANY-765 на пересобранный ANY-715

## Проверенная основа

- [PR #157](https://github.com/gushinets/payments-portal/pull/157): HEAD `ff4f4cd`, ветка `ANY-765`, текущая база — старая `ANY-715`.
- [PR #161](https://github.com/gushinets/payments-portal/pull/161): HEAD `8c49a84`, ветка `refactor/any715-mvp`; пока открыт, не merged.
- Собственная граница подтверждена: `76ea1a7..ff4f4cd` — ровно 16 коммитов, 155 изменённых файлов. Переносить их итоговый результат, а не полный diff #157 и не старую историю исправлений шага 8.
- Прочитаны [актуальный план ANY-765](https://github.com/gushinets/payments-portal/blob/ff4f4cd/docs/exec-plans/active/ANY-765-implementation-plan.md), [тикет](https://linear.app/paveldik/issue/ANY-765), ADR 0005 и связанные решения C1–C4. Сохраняются принятые условия покупки, финансовые идентичности, ограничения повторного CREATE и доверие к authenticated point URL без повторных self-ID проверок.

План актуализирован после проверки 2026-11-06. При проверке и правке плана код, ветки и PR не изменялись. Выбранный порядок: сохранить исходную ветку как `ANY-765-OLD`, закрыть старый PR #157 без merge, продолжить работу в `ANY-765` и открыть новый PR после переноса.

## Последовательность переноса

### 0. Сохранить ANY-765-OLD и подготовить текущую ANY-765

- Перед реализацией обновить удалённые ссылки и проверить HEAD `ANY-765` и #161. Проверить чистоту рабочего дерева и совпадение локальной `ANY-765` с исходным удалённым HEAD; локальные коммиты и незакоммиченные изменения не отбрасывать. Записать полный исходный SHA как `ANY765_ORIGINAL_SHA` и отдельно выбранный SHA новой базы. Если исходник изменился относительно `ff4f4cd`, уточнить границу собственного изменения шага 9 до переноса.
- Создать `ANY-765-OLD` на исходном HEAD `ANY-765` локально и на origin. Проверить, что обе резервные ссылки указывают ровно на `ANY765_ORIGINAL_SHA`. Если резервная ветка уже существует, сначала проверить её SHA; существующую резервную ветку с другим содержимым не перезаписывать.
- После подтверждения резервной ветки закрыть PR #157 без merge, указав сохранённый исходник `ANY-765-OLD` и предстоящую замену новым PR. Не удалять резервную ветку и не переоткрывать старый PR для новой реализации.
- Продолжить работу в текущей ветке `ANY-765`: после резервирования перестроить её локальную основу на принятый HEAD #161. Если #161 уже merged — использовать актуальный `main`, содержащий его принятый результат; при squash проверить состав изменений. Отдельную рабочую ветку `codex/...` не создавать. До итоговой проверки удалённую `ANY-765` не переписывать.
- Существующие стенды, БД и локальную конфигурацию сохранить: копия Git-ветки не является резервной копией окружения. Для нового кода подготовить изолированное окружение через repository harness с отдельными Compose/БД/портами; не запускать миграции на сохранённой БД. Рабочую настройку foreground timeout 60 секунд перенести в новое окружение.
- Переносить результат по подсистемам из итогового diff исходной ветки, разрешая пересечения в пользу архитектуры #161. Использовать `ANY-765-OLD` как неизменяемый источник переноса и сравнения.

**Проверка:** исходный SHA сохранён в локальной и удалённой `ANY-765-OLD`; PR #157 закрыт без merge; работа ведётся в `ANY-765` на записанной новой базе; существующие стенды сохранены, окружение переноса изолировано. В собственном diff нет возвращённой старой реализации шага 8.

### 1. Перенести сохранённую функциональность и схему

**Практически без изменений:** `technical_terms.py`, `evidence.py`, `purchase_terms.py`, `paid_cycles.py`, `paid_allowances.py`, `paid_contracts.py`, development fixture 100/300 и модели paid access.

**Адаптировать:** purchase contracts/service/composition, сохранив новые поля и поведение #161, включая nullable lifecycle и `agreement_closed`.

- Сохранить immutable `accepted-purchase:v2`, digest подтверждения, чтение v1 и точный idempotent replay. Старые покупки не получают придуманные лимиты.
- Сохранить классификацию циклов, frozen quantities и стабильные allowance IDs.
- Перенести [миграцию `20261031_0006`](https://github.com/gushinets/payments-portal/blob/ff4f4cd/apps/api/alembic/versions/20261031_0006_paid_access.py) после `20261028_0005`: эта база в #161 не изменилась. Сохранить preflight, immutable history, логическую уникальность allowance и monotonic guards.

**Проверки:** `test_any765_purchase_terms*`, `test_paid_access_policy.py`, `test_paid_access_terms_postgres.py`, `test_paid_access_migration_postgres.py`. Проверить upgrade с данных #161, чтение существующих v2, сохранение legacy UTC без преобразования в даты и отказ небезопасного downgrade.

### 2. Подключить paid writer к reconciliation #161

**Адаптировать:** [общий reconciliation](https://github.com/gushinets/payments-portal/blob/8c49a84/apps/api/app/domains/billing/reconciliation.py), его composition/contracts и `paid_access.py`.

**Заменить механизмом #161:** старую отдельную реализацию переходов из `reconciliation_facts.py`.

- Сохранить один claim/read/apply для HTTP, worker и operator, включая `ReconciliationResult`, leases, fences и защиту от stale ACTIVE.
- В normalizer #161 добавить только календарные возможности шага 9: lossless precision, включительный однодневный диапазон, calendar anchors и явно zoned конечный instant. Не выводить UTC deadline из date-only.
- Сохранить исправления #161: `3/1` → ENDED/BLOCKED; закрытый договор при недоступной подписке остаётся отрицательным фактом уже связанного объекта; отсутствующий `services` с отличающейся ценой → INCOMPLETE.
- Неопределённость календаря запрещает новый allowance; независимо доказанный product grant следует принятой политике шага 9.
- Применять paid projection, semantic revision, causal audit, outbox и deadlines в транзакции исходного факта. Единственный `commit_paid_state` не делает собственного commit.

**Проверки:** normalization/reconciliation suites плюс paid PostgreSQL. Отрицательные факты немедленно снимают доступ без продления trust; неполный собственный proof не продлевает шестичасовой lease. Проверить `0→1`, semantic no-op, переход в empty и rollback после промежуточных записей.

### 3. Интегрировать primary selection через общий inventory

**Адаптировать:** [общий `collect_inventory`](https://github.com/gushinets/payments-portal/blob/8c49a84/apps/api/app/composition/purchase_inventory.py), `inventory_contracts.py`, `discovery.py` и `background_recovery.py::apply_inventory`.

**Заменить механизмом #161:** старые `read_inventory_points`, `read_target_inventory`, отдельный background loop и source-fact application из `paid_inventory.py`.

- Общий inventory продолжает применять каждый известный объект через leased reconciliation **до следующего внешнего чтения**. Ошибка соседа или финального списка не отменяет уже сохранённый отрицательный факт и его paid revision/outbox.
- Добавить к результату bounded evidence для primary: product-scoped кандидаты, полнота, ссылки на committed observations и соответствующие fences/версии. Не применять source facts повторно.
- При eligible proof без primary ставить urgent hint существующей задаче `customer_inventory`. Первый primary выбирается после полного inventory; рекурсивного reconciliation → inventory → reconciliation с новым discovery не вводить.
- Финальный выбор перепроверяет актуальность evidence под user/product locks. Сохранить union с локальными кандидатами, отсутствие автоматического promotion и trusted-primary policy.
- Newcomer вызывает соответствующий review, сохраняя независимо подтверждённый primary. Постоянные bindings другого продукта остаются его bindings даже в review.

**Проверки:** `test_billing_scoped_inventory_postgres.py`, `test_paid_access_rebase_postgres.py`, `test_paid_access_inventory_failure_postgres.py`. Добавить ошибку именно следующего point-read после успешного owned block, оба порядка кандидатов, timeout/cleanup/final-list failure, смену membership и потерю claim. Проверить запрет первого primary при неполном relevant inventory; уже committed negative переживает последующий сбой inventory.

### 4. Адаптировать recovery, restrictions, operator и worker

**Recovery — использовать механизм #161, старую реализацию не переносить:** использовать `purchase_recovery.py` и `preparation.py` #161. Первое binding остаётся preparation-only; BOUND направляется в общий reconciliation. UNKNOWN не разрешает новый финансовый CREATE.

**Restrictions — адаптировать:** `customers.py`, `customer_reviews.py`, `customer_conflicts.py`, `financial.py` и `background_recovery.py`.

- Сохранить `restrict_subscription` #161, вращение fences и инвалидирование старых leases.
- Подключить paid commit к существующим транзакционным окончаниям после всех ограничений. Customer conflict снимает все зависимые продукты атомарно; product conflict ограничивает свою область.
- Старый `purchases/review.py` не должен заменить более новую restriction logic.

**Operator — адаптировать:** `operator_cases.py`, `operator_review.py`, `operator_contracts.py`, `billing_operator.py`.

- Сохранить общие `restore-original`/`bind-original`, точные related-case проверки и audit #161.
- Добавить сохранённый `select-primary` для уже связанной, свежепроверенной подписки. Разрешаемый primary-case отличать от финансового admission conflict; чужие reviews не очищать.

**Worker — адаптировать:** `work.py`, `jobs/billing.py`, `billing_worker.py`, queries очереди и `paid_deadlines.py`.

- Добавить локальные deadlines/repair без второго scheduler. Local reductions работают без LBX-конфигурации.
- Сохранить retry acknowledgement, generation/lease ownership, urgency и исправления #161, включая REV-8.
- Сохранить worker timeout 60 секунд и рабочий foreground override 60 секунд с Compose forwarding; application default foreground остаётся 10 секунд.

**Проверки:** recovery/operator/worker suites #161 и paid recovery/cadence/scope-conflict suites. Same-cycle recovery возвращает прежние IDs; доказанный следующий цикл создаёт один новый набор без backfill. Проверить stale ACTIVE после restriction/restore, независимость продуктов, provider-free expiry, restart/repair, SQL NULL/JSON null и гонку refresh/expiry.

### 5. Перенести authenticated read и кабинет

**Практически без изменений:** `paid_read.py`, `paid_router.py`, paid-read queries, `PaidProductAccess.tsx`, `use-paid-access.ts`, API adapter и locale copy.

**Адаптировать:** `AccountBilling.tsx`, purchase presentation, wiring/settings и документацию к polling-only базе #161.

- Сохранить локальный authenticated `GET /api/paid-access`, no-store, session guards и отсутствие LBX/Kernel вызовов.
- Просроченный необработанный deadline даёт `paid_access_deadline_pending`; GET не фильтрует документ и не пишет состояние.
- Генерировать OpenAPI/TypeScript через `npm run generate`. Сохранить Bundle 3, отсутствие выдуманного usage/remaining и различие confirmed empty/unavailable.
- Обновить существующий план ANY-765 и runbook под итоговую интеграцию.

**Проверки:** paid-read PostgreSQL, cabinet/session component tests, synthetic Playwright desktop/mobile и accessibility.

## Итоговая приёмка и публикация

- Во время этапов запускать адресные проверки. На собранном HEAD выполнить согласованный итоговый QA: два продукта, первый grant, block/unblock, ended, incomplete/outage, восстановление без нового allowance, следующий цикл, конкурентные обновления продуктов и атомарный outbox с сохранением delivery bookkeeping.
- Проверить сбой до commit и restart после commit: либо откатывается весь переход, либо факты/state/revision/outbox сохранены целиком. Rollback на чистую сборку #161 поверх заполненной v2/`0006` БД не считать допустимым откатом.
- Выполнить `npm run check` с worktree-local PostgreSQL и затронутые browser journeys. Отдельно проверить итоговый diff на возврат удалённых обработчиков и повторных source writers.
- В итоговом отчёте показать прирост рабочего кода относительно выбранной новой базы и изменение его объёма относительно `ANY-765-OLD`; тесты, документацию и generated-файлы посчитать отдельно. Для обоих сравнений использовать одинаковый набор путей и правила подсчёта. Объяснить новые интеграционные модули и проверить, что они не дублируют reconciliation, inventory, recovery, scheduler или source writer #161. Цель — сохранить функциональность шага 9 на общей реализации; произвольный лимит строк и новый общий рефакторинг не вводить.
- Реальный **LBX → authoritative observation → paid state/revision/outbox → authenticated API → кабинет** проверить отдельно на поддерживаемой покупке. Новые реальные billing mutations требуют отдельного разрешения. Недоступный checkpoint записать как BLOCKED/NOT_RUN; симуляция не закрывает live acceptance. ANY-819/821, Kernel enforcement и production enablement остаются отдельными задачами.
- После локальной проверки повторно сверить удалённую `ANY-765` с `ANY765_ORIGINAL_SHA`, сохранённым на этапе 0. При чужих новых коммитах остановить перезапись и сначала согласовать их включение. Проверить сохранность удалённой `ANY-765-OLD` и выбранную базу нового PR; если база обновилась, включить необходимые изменения и повторить затронутые проверки.
- Обновить существующую ветку с явной lease. Перед командой убедиться, что текущая ветка — `ANY-765`, HEAD соответствует проверенному результату, а `ANY765_ORIGINAL_SHA` содержит полный SHA из этапа 0. Не подменять его заново прочитанным удалённым HEAD ради успешного push:

  ```bash
  git push \
    --force-with-lease="refs/heads/ANY-765:${ANY765_ORIGINAL_SHA:?Original SHA from stage 0 is required}" \
    origin HEAD:refs/heads/ANY-765
  ```

- Создать новый Draft PR из `ANY-765` в `refactor/any715-mvp`, если #161 ещё открыт, либо в соответствующий `main` после его merge. В описании указать ANY-765, заменяемый PR #157, резервную ветку `ANY-765-OLD`, принятый результат и актуальные проверки. Указать ссылку на новый PR в закрытом #157. Проверить, что собственный diff нового PR содержит только шаг 9 и необходимую адаптацию к #161.
- После merge #161 перенести основание `ANY-765` на соответствующий `main` и сменить базу нового PR; при squash переносить только собственный результат шага 9. Проверить итоговый diff и обязательные CI на опубликованном HEAD и окончательной базе. До успешной приёмки PR остаётся Draft; старый #157 остаётся закрытым. Merge — после человеческого одобрения.
