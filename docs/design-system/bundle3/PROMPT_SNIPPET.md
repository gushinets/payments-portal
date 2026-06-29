# AnyToolAI — Bundle 3 Design System
# Вставь в начало промпта перед любой UI-задачей

## Identity
Dark premium AI-native. Arc Browser / Raycast / Notion AI energy.
Glass surfaces, gradient accent, ambient glows everywhere.

## Tokens

```
BG:        #0F0C29  (base)  →  layered with radial glows
Accent:    linear-gradient(135deg, #6366F1, #818CF8)  — ALWAYS gradient, never flat
Teal:      #5EEAD4  — live/active states only
Green:     #34D399  — success
Text:      #F0EFF8 / rgba(240,239,248,0.55) / rgba(240,239,248,0.30)
Border:    rgba(255,255,255,0.10) / 0.18 strong
Font:      Cabinet Grotesk 900 (headlines) · DM Sans 300/400/600 (body) · DM Mono (numbers)
```

## Glass rule (EVERY surface)

```css
/* Cards / panels */
background: rgba(255,255,255,0.07);
backdrop-filter: blur(16px);
border: 1px solid rgba(255,255,255,0.10);
border-radius: 16–20px;

/* Nav / headers */
background: rgba(15,12,41,0.85);
backdrop-filter: blur(20px);
border-bottom: 1px solid rgba(255,255,255,0.08);
```

## Ambient glow (EVERY screen bg)

```css
background:
  radial-gradient(ellipse at 70% 0%,  rgba(99,102,241,0.22) 0%, transparent 55%),
  radial-gradient(ellipse at 20% 80%, rgba(94,234,212,0.10) 0%, transparent 50%),
  #0F0C29;
```

## Buttons

```css
/* Primary — gradient always */
background: linear-gradient(135deg, #6366F1, #818CF8);
box-shadow: 0 4px 16px rgba(99,102,241,0.35);
border-radius: 8–10px;

/* Secondary — glass outlined */
background: rgba(255,255,255,0.07);
border: 1px solid rgba(255,255,255,0.18);
backdrop-filter: blur(8px);
border-radius: 8–10px;
```

## Border radius

```
Web cards:      16–20px   Extension cards: 10–12px
Mobile cards:   14–16px   Bubbles: 18px (tail corner: 4px)
Buttons:        8–10px    Pills/badges: 100px
Avatars:        50%       FAB: 50%
```

## Platform rules

### Web
- Bento grid: 3 cols, gap 10px, all cards glass
- Hero: col-span 3, grid 2-col inside, H1 in Cabinet Grotesk 900
- H1 accent word: italic gradient #818CF8→#5EEAD4
- Tools: glass cards with dot colour per category
- Max-width 1160px

### Extension popup
- Width 340px fixed, always dark
- Structure: header → active tool card → 2-col mini tools → full-width CTA → footer
- CTA: gradient button, border-radius 10px
- Glow orb top-right corner

### Mobile (WhatsApp structure)
- 4 screens: Tool List → Thread → Run/Result → Settings
- Avatars: 50% round, gradient fills
- My bubbles: gradient indigo, border-bottom-right-radius 4px
- Their bubbles: glass, border-bottom-left-radius 4px
- FAB: 50%, gradient, glow shadow
- Bottom nav: glass + blur + 24px safe area bottom padding
- Result card: full gradient with inner glass stat cells

## Font import

```html
<link href="https://fonts.googleapis.com/css2?family=Cabinet+Grotesk:wght@400;500;700;800;900&family=DM+Sans:opsz,wght@9..40,300;400;500;600&family=DM+Mono:wght@400;500&display=swap" rel="stylesheet">
```

## Don't
- No solid fills on any surface
- No flat accent colour (always gradient)
- No Inter / Roboto / system fonts
- No sharp card corners
- No missing backdrop-filter
- No plain #0F0C29 background without glows
