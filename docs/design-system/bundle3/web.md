# Bundle 3 — Public Portal and Application Layouts

Use [SKILL.md](SKILL.md) for visual/component/accessibility rules and
[tokens.json](tokens.json) for canonical values. The approved ANY-539 RU Portal
mockup, supplied as the local visual reference during implementation, defines the
visual target for HOME, TOOLS, PRODUCT and LK RU. Its example business facts and
runtime controls are not implementation authority. Preserve the current page
composition, routes, auth and per-product state semantics when applying style.

## Shared language

Both public and authenticated layouts use a deep navy page background, opaque
dark-blue surfaces, thin blue borders, amber primary actions, compact radii and
Manrope. Indigo is a restrained secondary accent, not the page-wide
identity. Flat backgrounds and panels are normal; shadows/glows are minimal.
Blur is optional for navigation and is not required on cards or workspaces.

Use semantic Bundle 3 tokens through generated CSS. Do not paste the mockup's
stylesheet, introduce its short variable names as another palette, or add a
page-local theme. Existing aliases remain compatible; the historical
`--acc-grad` and `--headline-grad` slots now resolve to flat amber fills.

## Public shell and navigation

- Center ordinary public content within the 1080px `maxWidth` token. Narrower
  reading, hero and product-detail widths may fit their content; do not force
  the application workspace into the same centered marketing container.
- Use approximately 40px desktop horizontal gutters, falling to 16–20px on
  mobile. Typical section spacing is 48–80px, with compact 12–16px group gaps
  and the 14px `gridGap` token for public product grids.
- Navigation is compact and sticky, approximately 62px high on desktop and
  54px on mobile when content fits. Allow growth/wrapping for translated text
  rather than clipping it to a fixed height.
- Use an opaque navy navigation surface and a thin bottom border. A near-opaque
  background with up to 12px backdrop blur is optional and needs an opaque
  fallback. Links use 13px body type, compact 8px corners and restrained hover
  surface changes; active links can use amber text with semantic current state.
- Logo treatment is compact, approximately 18px/800, with optional amber emphasis.
  Primary/secondary navigation actions share the normal button language.
- Keep mobile navigation and account actions reachable; collapsing a navigation
  group must preserve an accessible way to reach its destinations.

## Home and catalog

- The home hero is centered on the page background, with a clear display
  heading, supporting copy and compact grouped actions. A giant glass hero tile
  or a mandatory three-column bento composition is not required.
- Use the shared 32–56px display scale, weight 800 and approximately 1.08 line
  height. Amber heading emphasis is a text color, not a required gradient.
  Supporting hero copy may reach 18px; ordinary body text remains 13–15px.
- Product cards are flat `surfaceCard` surfaces with thin `border` outlines,
  14px `card` corners and approximately 24px padding. Supporting cards/panels
  may use 12–16px corners and 18–24px padding according to density.
- Product grids may use up to three columns where the content fits. Preserve
  the current product set and grouping; the mockup does not authorize additional
  products, badges or runtime availability claims.
- Hover uses a restrained surface/border change. Small motion is optional and
  must respect reduced motion. Do not require glass blur, glow or hover lift.
- Card links and secondary actions remain distinct semantic controls; do not
  copy clickable divs or nested interaction patterns from the mockup.

## Product detail

- Preserve the existing two-column hero/detail composition where it fits:
  explanatory content and actions beside a preview on desktop, stacked on mobile.
- Preview surfaces use opaque dark-blue levels, thin borders and 12–16px corners.
  Supporting feature cards are compact flat panels with restrained spacing.
- Product headings use 26–32px/700–800; supporting text uses the shared body
  scale. Actions use flat amber or bordered secondary treatment.
- Retain current truthful content, previews and safe destinations. Styling a
  demo control never authorizes an installation, purchase or product runtime.

## Authenticated application and cabinet

- Use the 220px `dashboardRailWidth` token for a narrow supporting rail beside
  a wide `minmax(0, 1fr)` workspace. The workspace is flat and may use available
  width rather than inheriting the centered public page container.
- Rail: opaque `surfaceCard`, thin separating border, approximately 28px 14px
  padding, compact 13px navigation rows and 8px control corners.
- Workspace: `background`, approximately 40px 44px desktop padding, 22–26px
  headings, readable 11–13px section labels and compact supporting copy.
- Account/identity context stays supporting content. Existing per-product
  surfaces retain their semantics and use flat 12–14px panels with approximately
  18–20px padding, 12px group gaps and around 32px between sections.
- Selected rail items may use the subtle amber emphasis fill and amber text,
  alongside an explicit current-state indicator. Product state uses labels and
  semantic status tokens, never brand color alone.
- The mockup's subscription banners, payment facts and usage bars do not
  establish live data. Preserve unavailable, unknown and not-ready meanings.
- Auth/recovery forms and dialogs share the same palette, body family, opaque
  surfaces, compact radii and focus rules. Their interaction behavior stays owned
  by the existing implementation.

## Responsive and accessible behavior

- At 860px or earlier when content needs it, collapse product/detail grids to
  one column and move rail content above the workspace. Use about 20px mobile
  workspace padding. At 520px, stack/full-width actions where necessary.
- Permit wrapping and avoid horizontal overflow for translated text, legal
  content and account identifiers. Keep logical reading/focus order.
- Compact visual controls must still have usable touch targets, semantic labels,
  keyboard operation and a clear focus outline. Dialog focus behavior is required.
- Use `textSecondary` for readable small metadata and section labels. The
  mockup's tertiary color maps to `textDisabled` for disabled/decorative uses;
  it is not permission for low-contrast ordinary text.
- Keep WCAG AA text/control contrast and pair state colors with text/icons.
  Essential control boundaries can use `borderStrong`; subtle card borders are
  decorative grouping, not the sole state or interaction cue.
- Font loading belongs to the application integration step and must use the
  repository-approved mechanism. Do not copy or add remote CSS font imports.

Step 10 established this authority and generated tokens; Step 11 applied the
rules and originally loaded Plus Jakarta Sans. The subsequent ANY-636 correction
loads Manrope through `next/font/google` for both Cyrillic and Latin text.
