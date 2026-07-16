# Repository Quality Score

Status: maintained baseline
Last verified: 2026-07-14

| Area | Initial | Current | Target | Evidence |
|---|---:|---:|---:|---|
| Knowledge and documentation | C | A | A | `npm run docs:check` |
| Reproducible development | C | A | A | `npm run repo:doctor`, worktree smoke |
| Backend correctness | B | A | A | API and PostgreSQL suites |
| Frontend verification | D | B | B | Playwright critical journeys |
| Architecture enforcement | D | B | B | import and size checks |
| Observability | D | B | B | Loki, Prometheus, and Tempo queries |
| Security guardrails | B | A | A | redaction tests and high-risk ownership |
| Agent delivery loop | D | B | A | [PR #9](https://github.com/gushinets/payments-portal/pull/9) completed the trial with autonomy and overall grade B; follow-up debt is ANY-123-ANY-125 |

Grades must link to executable evidence. Weekly gardening checks may improve the
grade or open maintenance work, but must never hide a regression by lowering the
target.
