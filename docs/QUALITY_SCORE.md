# Repository Quality Score

Status: maintained baseline
Last verified: 2026-07-11

| Area | Initial | Current | Target | Evidence |
|---|---:|---:|---:|---|
| Knowledge and documentation | C | A | A | `npm run docs:check` |
| Reproducible development | C | A | A | `npm run repo:doctor`, worktree smoke |
| Backend correctness | B | A | A | API and PostgreSQL suites |
| Frontend verification | D | B | B | Playwright critical journeys |
| Architecture enforcement | D | B | B | import and size checks |
| Observability | D | B | B | Loki, Prometheus, and Tempo queries |
| Security guardrails | B | A | A | redaction tests and high-risk ownership |
| Agent delivery loop | D | B | A | PR/CI workflow complete; ANY-116 trial pending |

Grades must link to executable evidence. Weekly gardening checks may improve the
grade or open maintenance work, but must never hide a regression by lowering the
target.
