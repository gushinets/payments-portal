# Design System

Status: authoritative entry point
Last updated: 2026-10-08

AnyToolAI Portal UI follows AnyToolAI Bundle 3, the single canonical
implementation design system. The approved ANY-539 RU Portal mockup, supplied
and directly inspected as a local input-only visual reference, is the product
and visual target; Bundle 3 encodes its deep navy background,
opaque dark-blue surfaces, thin blue borders, amber primary actions, compact
radii/spacing and Manrope typography. Public discovery, product details and the
account/auth cabinet share this language. Indigo is a restrained secondary
accent. Shadows are minimal; subtle navigation blur is optional.

ANY-636 Step 10 supersedes the older mandatory indigo gradients, radial glows,
glass/bento cards, large radii and blur-heavy surfaces. Flat backgrounds,
opaque panels and flat amber actions are normal Bundle 3 styling. This step
recalibrated the canonical design system. Step 11 applied it across the active
Portal with Plus Jakarta Sans through `next/font/google`. The subsequent
ANY-636 Cyrillic coverage correction replaces that family with Manrope for
headlines and body text across all seven locales: Plus Jakarta Sans lacks
basic Cyrillic U+0400–U+045F. Loading still uses `next/font/google`, without
the mockup's remote CSS import or a parallel token authority.

The current composition is product-first home/catalog, substantial two-column
product screens with labeled schematic illustrations and supporting content,
a presentation-only pricing placeholder, direct auth entry, and a
product-centric cabinet with compact identity context. Per-product
commercial/access/usage/action slots are the durable presentation surface for
later parent ANY-504 Steps 6–10; missing business sources remain honest
not-ready/unknown/unavailable states. Mobile layouts stack the content while
preserving discovery, auth and product navigation.

Before UI work, read:

1. [Bundle 3 overview](design-system/bundle3/README.md)
2. [Full rules](design-system/bundle3/SKILL.md)
3. [Web layout rules](design-system/bundle3/web.md)
4. [Machine-readable tokens](design-system/bundle3/tokens.json)

The machine-readable tokens are canonical for values consumed by the app.
The existing repository generator produces
[web token CSS](../apps/web/src/app/tokens.generated.css); never edit that output
by hand. Preserve visible keyboard focus, semantic controls, sufficient text
and control contrast, usable touch targets, responsive single-column layouts
and state meaning beyond color. UI changes must include desktop and mobile
screenshots plus accessibility results.

The mockup is visual/product evidence only. Its provider names, tariffs,
subscription/access states, usage/quota values, metrics, unsupported product
availability, roadmap products and legal/privacy claims are not business or
runtime authority. Pricing navigation does not authorize commercial offers or
purchase controls; those remain parent ANY-504 Steps 6 and 7 respectively.

Ordinary Portal-owned copy follows the active route locale (`en`, `fr`, `it`,
`de`, `es`, `ru`, or `pt`) within the implemented `ru` contour. Locale does not
select a contour or data plane. Canonical RU legal content and acceptance text
remain source-owned and Russian. Billing, paid-access, and usage/quota panels
must present unavailable/unknown states without implying no subscription, no
access, or zero usage/quota. See the
[as-built RU Portal 4F handoff](product/ru-mvp.md).
