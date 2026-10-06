# Design System

Status: authoritative entry point
Last updated: 2026-10-06

AnyToolAI Portal UI follows AnyToolAI Bundle 3: a dark AI-native glass and bento
system with indigo gradients and restrained teal status accents. The public
landing, product discovery/detail pages, and account/auth cabinet share this
system; 4F introduces no replacement tokens or parallel visual framework.

Before UI work, read:

1. [Bundle 3 overview](design-system/bundle3/README.md)
2. [Full rules](design-system/bundle3/SKILL.md)
3. [Web layout rules](design-system/bundle3/web.md)
4. [Machine-readable tokens](design-system/bundle3/tokens.json)

The machine-readable tokens are canonical for values consumed by the app. UI
changes must include desktop and mobile screenshots plus accessibility results.
Ordinary Portal-owned copy follows the active route locale (`en`, `fr`, `it`,
`de`, `es`, `ru`, or `pt`) within the implemented `ru` contour. Locale does not
select a contour or data plane. Canonical RU legal content and acceptance text
remain source-owned and Russian. Billing, paid-access, and usage/quota panels
must present unavailable/unknown states without implying no subscription, no
access, or zero usage/quota. See the
[as-built RU Portal 4F handoff](product/ru-mvp.md).
