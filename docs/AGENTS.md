# Documentation Agent Guide

Engineering documentation is English. Russian is allowed only inside
`docs/legal/ru/**`, where the content is a versioned legal artifact.

- Keep `AGENTS.md` files navigational and concise.
- Add authoritative documents to `docs/README.md`.
- Use relative links and run `npm run docs:check`.
- Mark planned behavior explicitly; never describe it as implemented.
- Do not edit `docs/generated` directly.
- Legal changes require a new version, regenerated manifest, and explicit legal
  review.
