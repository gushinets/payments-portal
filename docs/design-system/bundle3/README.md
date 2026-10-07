# AnyToolAI Bundle 3 Design System

Bundle 3 is the single canonical design system for the AnyToolAI Portal. It
originated as a local copy of the web-relevant files from:

```text
D:\Work\AI\Design system\files_Bandl_3.zip
```

ANY-636 Step 10 recalibrates that system to the approved RU Portal mockup
attached to ANY-539: deep navy, opaque dark-blue surfaces, thin blue borders,
amber primary actions, compact
radii/spacing and Plus Jakarta Sans. The former mandatory indigo glass/bento
identity is superseded. The mockup supplies visual direction, not provider,
commercial, access, usage, availability or legal facts.

Canonical files:

- [SKILL.md](SKILL.md) - visual, component and accessibility rules.
- [PROMPT_SNIPPET.md](PROMPT_SNIPPET.md) - compact prompt/instruction snippet.
- [web.md](web.md) - public and authenticated application layout rules used by
  [apps/web](../../../apps/web/).
- [tokens.json](tokens.json) - the only machine-readable token authority.

The [design entry point](../../DESIGN.md) and
[web agent guide](../../../apps/web/AGENTS.md) use these same rules. Run
`npm run generate` to refresh
[generated token CSS](../../../apps/web/src/app/tokens.generated.css) through
the existing [repository generator](../../../scripts/repo.py). Do not edit
generated CSS or introduce page-local palettes. Existing CSS aliases remain
available; token values, font families, layout dimensions and radii come from
this one source.

Step 10 changes this authority and its generated tokens. Step 11 applies the
rules and approved font loading to the existing pages; product, route, auth,
session, locale and backend semantics remain unchanged.

The original archive also contains `extension.md` and `mobile.md`; they are not
included here because this repository implements the AnyToolAI Portal web
surface: public product discovery, direct account/auth entry, and the account
cabinet. Bundle 3 remains the shared design system. The implemented contour is
`ru`; ordinary UI route locales remain independent of that contour, and
canonical legal content remains RU-only. See the
[as-built RU Portal 4F handoff](../../product/ru-mvp.md).
