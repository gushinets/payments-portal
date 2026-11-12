# ANY-766 test runtime

Status: complete; local validation passed. CI validation is pending.

## Objective and scope

Implement the measured test acceleration without dependency changes.
Keep all business assertions, fresh scenario setup, real
transactions and explicit migration tests. Existing edits to the main ANY-766
implementation plan are outside this change.

## Decisions

The prior characterization and prototype regression are recorded in the chat.
Use bounded independent processes and copies of a real migrated schema/seed
template. Use a separate disposable tmpfs server; preserve the development DB.
Keep the fast partition serial; the complete API command then runs the parallel
PostgreSQL partition and combines both reports.
Do not cache purchases, share mutable fixtures, replace commit with rollback,
or relax deadlines. Keep actual run commands and results in the chat.

## Implementation and validation

- [x] Session-owned unique databases and a migrated schema/seed template.
- [x] Bounded independent pytest processes through canonical test commands,
      exact collection parity and combined JUnit output; no new dependency.
- [x] Separate local test Compose server and tmpfs in the CI test service.
- [x] Focused isolation, lifecycle, dispatch and failure-reporting checks.
- [x] Final accelerated regression and preservation of pre-existing edits.

Production code, migrations, business fixtures and timeout values are unchanged.
Browser and external-provider journeys are not applicable to this tooling change.
