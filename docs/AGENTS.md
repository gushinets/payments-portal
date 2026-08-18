# Documentation Agent Guide

Engineering documentation is English. Customer-facing legal source lives under
`docs/legal/<contour>/**` and may use that contour's language. The only
existing tree is `docs/legal/ru`.

- Keep `AGENTS.md` files navigational and concise.
- Add authoritative documents to `docs/README.md`.
- Use relative links and run `npm run docs:check`.
- Mark planned behavior explicitly; never describe it as implemented.
- Do not edit `docs/generated` directly.
- Legal changes require a new version, regenerated manifest, and explicit legal
  review.
