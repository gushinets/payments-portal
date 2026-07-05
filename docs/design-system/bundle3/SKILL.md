---
name: anytoolai-bundle3-design
description: >
  Design system for AnyToolAI — Bundle 3 (Glassmorphism + Bento Grids).
  Dark premium AI-native aesthetic: deep indigo backgrounds, backdrop-filter blur
  on all surfaces, gradient accent #6366F1→#818CF8, teal highlights #5EEAD4.
  Use this skill for ANY UI task: landing page, browser extension popup, mobile
  screens, components, cards, modals, forms, or any visual output for AnyToolAI.
  Trigger on: "make a page", "build a component", "add a screen", "style this",
  "create UI", "extension popup", "mobile screen", "landing", "dashboard",
  "dark theme", "glass UI". Never freestyle tokens — always load this skill first.
  For repo-local web details read: web.md. The source archive also had
  extension/mobile references, but this repository only keeps the web rules.
---

# AnyToolAI — Bundle 3 Design System
## Glassmorphism + Bento Grids · Dark AI-Native

Вдохновение: Arc Browser, Raycast, Notion AI, Framer.
Три платформы — единый DNA: стекло, градиент, глубина.

---

## 1. Colour Tokens

```css
:root {
  /* Backgrounds — layered depth */
  --bg:        #0F0C29;   /* base, deepest */
  --bg2:       #1a1550;   /* secondary sections */
  --surf1:     rgba(255,255,255,0.07);   /* cards, panels */
  --surf2:     rgba(255,255,255,0.11);   /* hover state */
  --surf3:     rgba(255,255,255,0.16);   /* active / pressed */

  /* Borders */
  --border:    rgba(255,255,255,0.10);
  --border2:   rgba(255,255,255,0.18);   /* prominent */

  /* Text */
  --txt:   #F0EFF8;                      /* primary */
  --txt2:  rgba(240,239,248,0.55);       /* secondary */
  --txt3:  rgba(240,239,248,0.30);       /* disabled / placeholder */

  /* Accent — gradient, never flat */
  --acc:       #818CF8;                  /* light indigo */
  --acc2:      #6366F1;                  /* deep indigo */
  --acc-grad:  linear-gradient(135deg, #6366F1 0%, #818CF8 100%);
  --acc-glow:  rgba(99,102,241,0.25);

  /* Teal highlight — use sparingly */
  --teal:      #5EEAD4;
  --teal-glow: rgba(94,234,212,0.15);

  /* Semantic */
  --green:     #34D399;
  --green-bg:  rgba(52,211,153,0.15);
  --green-bdr: rgba(52,211,153,0.25);
  --red:       #F87171;
  --red-bg:    rgba(248,113,113,0.15);
  --amber:     #FBBF24;
}
```

---

## 2. Typography

| Role           | Font              | Weight | Size    | Tracking   |
|----------------|-------------------|--------|---------|------------|
| Display / H1   | Cabinet Grotesk   | 900    | 44–56px | −0.04em    |
| H2 / Section   | Cabinet Grotesk   | 800    | 26–36px | −0.03em    |
| H3 / Card name | Cabinet Grotesk   | 700    | 15–18px | −0.02em    |
| Body           | DM Sans           | 400    | 13–14px | 0          |
| Body light     | DM Sans           | 300    | 12–13px | 0          |
| Label / tag    | DM Sans           | 600    | 10–11px | +0.08em    |
| Mono / numbers | DM Mono           | 400    | 10–12px | 0          |

```html
<link href="https://fonts.googleapis.com/css2?family=Cabinet+Grotesk:wght@400;500;700;800;900&family=DM+Sans:opsz,wght@9..40,300;400;500;600&family=DM+Mono:wght@400;500&display=swap" rel="stylesheet">
```

---

## 3. Glass Surface Pattern

**Core rule**: every elevated surface gets glass treatment — no solid fills.

```css
/* Level 1 — subtle (nav, headers) */
.glass-1 {
  background: rgba(255,255,255,0.04);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  border-bottom: 1px solid var(--border);
}

/* Level 2 — cards, panels */
.glass-2 {
  background: rgba(255,255,255,0.07);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  border: 1px solid var(--border);
  border-radius: 16px;
}

/* Level 3 — modals, drawers */
.glass-3 {
  background: rgba(255,255,255,0.11);
  backdrop-filter: blur(24px);
  -webkit-backdrop-filter: blur(24px);
  border: 1px solid var(--border2);
  border-radius: 20px;
}
```

---

## 4. Ambient Glow

Every screen needs at least one glow layer behind content:

```css
/* Typical page bg */
.page-bg {
  background:
    radial-gradient(ellipse at 70% 0%,   rgba(99,102,241,0.20) 0%, transparent 55%),
    radial-gradient(ellipse at 20% 80%,  rgba(94,234,212,0.10) 0%, transparent 50%),
    #0F0C29;
}

/* Hero-only stronger glow */
.hero-glow {
  background:
    radial-gradient(ellipse at 50% -10%, rgba(99,102,241,0.30) 0%, transparent 60%),
    #0F0C29;
}

/* Inline decorative orb */
.glow-orb {
  position: absolute;
  width: 300px; height: 300px;
  border-radius: 50%;
  background: radial-gradient(circle, var(--acc-glow) 0%, transparent 70%);
  pointer-events: none;
}
```

---

## 5. Border Radius

| Element                  | Radius  |
|--------------------------|---------|
| Buttons                  | 8–10px  |
| Input fields             | 8px     |
| Cards / panels (web)     | 16–20px |
| Bento hero card          | 24px    |
| Stat mini cards          | 12px    |
| Filter pills / badges    | 100px   |
| Avatars                  | 50%     |
| Mobile bubbles (me)      | 18px, bottom-right 4px |
| Mobile bubbles (them)    | 18px, bottom-left 4px  |
| Mobile cards             | 14–16px |
| FAB                      | 50%     |

---

## 6. Core Components

### Button

```css
/* Primary — always gradient */
.btn-primary {
  background: var(--acc-grad);
  color: #fff;
  border: none;
  border-radius: 8px;
  padding: 10px 22px;
  font-family: 'DM Sans', sans-serif;
  font-size: 13px; font-weight: 600;
  cursor: pointer;
  box-shadow: 0 4px 16px rgba(99,102,241,0.35);
  transition: opacity 0.15s, box-shadow 0.15s;
}
.btn-primary:hover {
  opacity: 0.9;
  box-shadow: 0 6px 24px rgba(99,102,241,0.5);
}

/* Secondary — glass outlined */
.btn-secondary {
  background: rgba(255,255,255,0.07);
  color: var(--txt);
  border: 1px solid var(--border2);
  border-radius: 8px;
  padding: 10px 22px;
  font-size: 13px; font-weight: 400;
  cursor: pointer;
  backdrop-filter: blur(8px);
  transition: background 0.15s;
}
.btn-secondary:hover { background: rgba(255,255,255,0.12); }
```

### Card (Bento)

```css
.bento-card {
  background: rgba(255,255,255,0.07);
  backdrop-filter: blur(16px);
  border: 1px solid rgba(255,255,255,0.12);
  border-radius: 20px;
  padding: 20px;
  transition: background 0.2s, transform 0.2s;
}
.bento-card:hover {
  background: rgba(99,102,241,0.10);
  border-color: rgba(129,140,248,0.25);
  transform: translateY(-2px);
}
```

### Status Badge

```css
.badge {
  display: inline-flex; align-items: center; gap: 4px;
  padding: 3px 10px; border-radius: 100px;
  font-size: 9px; font-weight: 700;
  font-family: 'DM Mono', monospace;
  letter-spacing: 0.05em; text-transform: uppercase;
}
.badge-done    { background: var(--green-bg);  color: var(--green); border: 1px solid var(--green-bdr); }
.badge-running { background: rgba(129,140,248,0.15); color: var(--acc); border: 1px solid rgba(129,140,248,0.3); }
.badge-live    { background: rgba(94,234,212,0.12); color: var(--teal); border: 1px solid rgba(94,234,212,0.25); }
```

### Stats Strip (Bento)

```css
.stats-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
}
.stat-cell {
  background: rgba(255,255,255,0.06);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 12px 14px;
}
.stat-val {
  font-family: 'Cabinet Grotesk', sans-serif;
  font-size: 24px; font-weight: 900;
  color: var(--txt); letter-spacing: -0.04em; line-height: 1;
  margin-bottom: 3px;
}
.stat-val span { color: var(--acc); font-style: italic; }
.stat-lbl { font-size: 10px; color: var(--txt3); }
.stat-trend { font-size: 10px; color: var(--green); font-weight: 600; }
```

### Eyebrow (hero pill)

```css
.eyebrow {
  display: inline-flex; align-items: center; gap: 6px;
  background: rgba(99,102,241,0.12);
  border: 1px solid rgba(129,140,248,0.25);
  border-radius: 100px;
  padding: 5px 14px 5px 8px;
  font-size: 11px; font-weight: 600;
  color: var(--acc); letter-spacing: 0.06em; text-transform: uppercase;
  margin-bottom: 20px;
}
.eyebrow-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--teal); }
```

---

## 7. Do / Don't

| ✅ Do | ❌ Don't |
|-------|---------|
| `backdrop-filter: blur()` on every surface | Solid opaque fills |
| Gradient buttons with glow shadow | Flat colour buttons |
| Ambient radial glows in bg | Plain `#0F0C29` without glows |
| Cabinet Grotesk 900 on headlines | Inter, Roboto, system fonts |
| Gradient accent `#6366F1→#818CF8` | Flat `#818CF8` without gradient |
| Teal `#5EEAD4` for live/active states | Overusing teal everywhere |
| Rounded corners everywhere | Sharp corners |
| Gradient avatars | Flat colour avatars |
| Glass FAB + accent glow shadow | Flat FAB |
| `letter-spacing: -0.04em` on display | Default tracking |
| DM Mono for all numbers/time | DM Sans for numbers |

---

## 8. Platform Details

Read the relevant repo-local file before building:

| Platform | File | Key notes |
|----------|------|-----------|
| Web / Landing | [web.md](web.md) | Bento grid, hero, nav, tools grid |
| Extension popup | not included in this repo | 340px fixed, glass dark, single CTA |
| Mobile iOS | not included in this repo | WhatsApp structure, glass bubbles |
