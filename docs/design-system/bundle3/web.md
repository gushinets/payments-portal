# Bundle 3 — Web / Landing Page

## Layout

```
max-width: 1160px, centered
section padding: 80px 40px
nav padding: 20px 40px
```

## Nav

```css
nav {
  position: sticky; top: 0; z-index: 100;
  background: rgba(15,12,41,0.85);
  backdrop-filter: blur(20px);
  border-bottom: 1px solid rgba(255,255,255,0.08);
  padding: 20px 40px;
  display: flex; align-items: center; justify-content: space-between;
}
.logo {
  font-family: 'Cabinet Grotesk', sans-serif;
  font-size: 17px; font-weight: 900; color: #F0EFF8;
  letter-spacing: -0.04em;
}
.logo span { color: #818CF8; }
.nav-link { font-size: 12px; color: rgba(240,239,248,0.45); text-decoration: none; }
```

## Hero (Bento 3-col)

Structure: full-width hero card (col-span 3) + 3 feature cards below.

```css
.bento-grid {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  gap: 10px;
}
.hero-card {
  grid-column: 1 / -1;
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 32px;
  align-items: center;
  background: rgba(255,255,255,0.06);
  backdrop-filter: blur(20px);
  border: 1px solid rgba(255,255,255,0.12);
  border-radius: 24px;
  padding: 36px 40px;
}
```

Hero H1 pattern:
```html
<h1 class="hero-h1">
  Your arsenal of<br>
  <em class="h1-grad">AI solutions</em>
</h1>
```
```css
.hero-h1 {
  font-family: 'Cabinet Grotesk', sans-serif;
  font-size: 52px; font-weight: 900;
  letter-spacing: -0.04em; line-height: 0.95;
  color: #F0EFF8;
}
.h1-grad {
  font-style: italic; font-weight: 800;
  background: linear-gradient(120deg, #818CF8 0%, #5EEAD4 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}
```

## Tools Grid

Same glass-card pattern, 3 columns:

```css
.tools-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 10px;
}
.tool-card {
  background: rgba(255,255,255,0.05);
  backdrop-filter: blur(12px);
  border: 1px solid rgba(255,255,255,0.10);
  border-radius: 18px;
  padding: 22px 20px;
  cursor: pointer;
  transition: background 0.2s, border-color 0.2s, transform 0.2s;
}
.tool-card:hover {
  background: rgba(99,102,241,0.10);
  border-color: rgba(129,140,248,0.28);
  transform: translateY(-2px);
}
.tool-icon-wrap {
  width: 40px; height: 40px; border-radius: 10px;
  background: rgba(255,255,255,0.08);
  border: 1px solid rgba(255,255,255,0.10);
  display: flex; align-items: center; justify-content: center;
  font-size: 18px; margin-bottom: 16px;
}
.tool-tag {
  font-size: 10px; font-weight: 600;
  color: #818CF8; letter-spacing: 0.08em; text-transform: uppercase;
}
.tool-dot {
  width: 8px; height: 8px; border-radius: 50%;
  margin-bottom: 14px;
  /* colour per category: acc / teal / amber */
}
```

## Feature Cards (below hero)

```css
.feat-card {
  background: rgba(255,255,255,0.05);
  backdrop-filter: blur(16px);
  border: 1px solid rgba(255,255,255,0.10);
  border-radius: 20px;
  padding: 22px 20px;
}
.feat-metric {
  font-family: 'Cabinet Grotesk', sans-serif;
  font-size: 28px; font-weight: 900;
  color: #F0EFF8; letter-spacing: -0.04em;
  margin-bottom: 2px;
}
.feat-metric span { color: rgba(240,239,248,0.35); font-size: 16px; }
```

## Page Background

Always use layered radial glows, not flat colour:

```css
body {
  background:
    radial-gradient(ellipse at 65% -5%,  rgba(99,102,241,0.22) 0%, transparent 50%),
    radial-gradient(ellipse at 15% 85%,  rgba(94,234,212,0.12) 0%, transparent 48%),
    linear-gradient(160deg, #0F0C29 0%, #1a1550 60%, #0a1a3a 100%);
}
```
