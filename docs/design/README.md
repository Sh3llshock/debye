# Debye design

Visual language for the staff page (`/staff`), the partner page (`/partner/:id`) and the resident's WhatsApp thread. It follows [reltix.de](https://www.reltix.de/), scaled up so it reads from the back of a large hall.

- Tokens: [`tokens.json`](tokens.json). Frontend maps them into `frontend/src/theme.ts`; components never hard-code colours.
- Figma: _link added once the file exists_.

## The look in one paragraph

Warm cream page (`#FAF6F2`), white cards with a thin warm border and a soft aubergine-tinted shadow, deep aubergine (`#330933`) for headings, primary buttons and the Debye mark. Headings are a classic serif (Baskervville, semibold, tight tracking); everything else is IBM Plex Sans. Generous whitespace, rounded corners (16–20 px), few colours. Colour other than aubergine only carries meaning: status, priority and who did what.

## Fonts

One Google Fonts link (in `tokens.json → font.googleFonts`):

| Role | Family | Use |
|---|---|---|
| display | Baskervville 600 | page titles, card titles, the big numbers in headings |
| sans | IBM Plex Sans 400/500/600 | all UI text, buttons, labels, stats |
| mono | IBM Plex Mono | IDs (`case_0001`), invoice numbers, JSON payload viewer |

Projector scale: body text 20 px, never below 15 px. Page title 48 px, card titles 28 px.

## Colour

| Token | Hex | Use |
|---|---|---|
| `brand.aubergine` | `#330933` | primary buttons, headings, top bar, Debye avatar |
| `brand.violet` | `#8332AC` | links, focus ring, "new" state, live highlight |
| `surface.page` | `#FAF6F2` | page background |
| `surface.card` | `#FFFFFF` | cards |
| `border.default` | `#E7DFD7` | card and input borders, dividers |
| `text.body` / `text.muted` | `#1A1A1A` / `#6B6B6B` | copy / secondary copy |

**Status pills** (`color.status.*`, each has `fg` + `bg`): new/requested violet, accepted/scheduled blue, slots_proposed/in_progress amber, completed/invoiced green, closed grey, declined red. Pill = full radius, 8 px dot in `fg`, label in `fg` on `bg`.

**Priority**: `urgent` is the only filled red element on the page (white on `#B42318`). Use it sparingly so it pops.

**Timeline actors** (`color.actor.*`): 40 px circle icon. Debye = aubergine with the Debye mark, resident = green, partner = amber with a wrench, staff = blue with a briefcase, system = grey with a gear.

## Components

- **Button primary**: aubergine, white text, 16 px radius, 16×28 padding, optional trailing arrow (→), like reltix's "Jetzt anfragen".
- **Button secondary**: white with 1.5 px aubergine border.
- **Tag / eyebrow**: thin aubergine outline pill, 14 px text (reltix uses these above section titles).
- **Card**: white, 1 px `#E7DFD7` border, 20 px radius, 32 px padding, `shadow.card`. Title in Baskervville 28 px.
- **Inverse card**: aubergine background, white text. Use for the one thing that needs attention (approval card, "zero forms" counter).
- **Slot chip** (partner page): big tappable tile, 20 px text; selected = aubergine fill.
- **Live timeline item**: slides in from below and flashes violet-soft for 1.2 s.

## Debye mark

Aubergine circle, white serif lowercase **d**, small violet spark at the top right. Used as the WhatsApp profile picture, the actor icon for Debye in the timeline and in the top bar next to "Debye · AI assistant". The top bar may carry a small "for reltix · centrix" text reference; we never use the reltix logo as our own.

## Layout

1440 px frames, 48 px page gutter, 32 px column gap, 80 px top bar (aubergine, white text). Staff page: unit + case on the left, live timeline + WhatsApp thread on the right.
