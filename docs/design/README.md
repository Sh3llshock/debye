# Debye design

Visual language for the staff page (`/staff`), the partner page (`/partner/:id`) and the resident's WhatsApp thread. It follows [reltix.de](https://www.reltix.de/), scaled up so it reads from the back of a large hall.

- Tokens: [`tokens.json`](tokens.json). Frontend maps them into `frontend/src/theme.ts`; components never hard-code colours.
- Figma: **[Debye (AI assistant)](https://www.figma.com/design/vW4cyvW7lLOjYGOg7Ul1iJ)** (one page "Debye", four sections).
- Language: staff and partner UI in English (for the judges), resident WhatsApp copy in German.

## Frames and exports

| Figma section → frame | PNG | What it shows |
|---|---|---|
| 00 Foundations | [foundations.png](foundations.png) | Debye mark, buttons, status pill set, colours, type scale |
| 01 Staff → Staff / Case detail | [staff-case-detail.png](staff-case-detail.png) | `/staff/cases/case_0001` in the "invoiced" moment: unit card, case card (lifecycle bar, priority, cost bearer, partner, visit, approval rule), zero-forms counter, live timeline with actor icons (newest item highlighted), WhatsApp thread preview, "why this partner" top 3, consent record, documents with the new invoice |
| 01 Staff → Staff / Cases list | [staff-cases-list.png](staff-cases-list.png) | `/staff` cases table, approval card for a €620 case above the €500 limit, weekly stats |
| 02 Partner → Partner / 1 · New job | [partner-1-new.png](partner-1-new.png) | Job inbox + job detail with only consented context, Accept / Decline |
| 02 Partner → Partner / 2 · Accepted → pick slots | [partner-2-accepted-slot-picker.png](partner-2-accepted-slot-picker.png) | 3×3 tap-to-select slot grid, "Send 2 slots to tenant" |
| 02 Partner → Partner / 3 · Slots proposed | [partner-3-slots-proposed.png](partner-3-slots-proposed.png) | Proposed slots, waiting for the tenant on WhatsApp |
| 02 Partner → Partner / 4 · Scheduled → mark as done | [partner-4-scheduled-mark-done.png](partner-4-scheduled-mark-done.png) | Confirmed slot, photo + invoice PDF upload tiles, notes, "Mark as done" |
| 02 Partner → Partner / 5 · Completed | [partner-5-completed.png](partner-5-completed.png) | Success state, filed documents, tenant confirmation |
| 03 Resident WhatsApp → 1–6 | [whatsapp-flow.png](whatsapp-flow.png) | Voice note + photo → one question with reply buttons → consent buttons → slot list message (sheet open) → booked + "Ist es wieder warm?" → closed; Debye profile page |
| Debye mark | [debye-avatar.svg](debye-avatar.svg), [debye-avatar-256.png](debye-avatar-256.png) | Use the PNG as the WhatsApp Business profile picture, the SVG in the web UI |

### Notes for the frontend

- Page backgrounds `#FAF6F2`, top bar on `/staff` is aubergine with white text; on `/partner` it is white with a bottom border and the partner's own initials badge, plus a small "via Debye · for reltix" pill.
- Staff case detail grid at 1440: three columns 400 / 480 / 400 with 32 gaps, then a second row of three equal cards.
- Timeline item: 48 px actor icon, name in the actor colour (16 px semibold), time in mono, text 18 px. The newest item gets the `violetSoft` background and a "New" pill.
- Slot picker chips: 20–21 px text, 16 px radius, selected = aubergine fill with a white check.
- WhatsApp screens are reference mockups for the agent coder's message copy and button labels (button ids per `interfaces.md §3.6`).

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

Aubergine circle, white serif lowercase **d**, small lilac (`#C9A3E0`) spark at the top right. Used as the WhatsApp profile picture, the actor icon for Debye in the timeline and in the top bar next to "Debye · AI assistant". The top bar may carry a small "for reltix · centrix" text reference; we never use the reltix logo as our own.

## Layout

1440 px frames, 48 px page gutter, 32 px column gap, 80 px top bar (aubergine, white text). Staff page: unit + case on the left, live timeline + WhatsApp thread on the right.

## Mascot

A friendly lowercase serif **d** with the lilac spark and a tiny wrench: the helper living in residents' WhatsApp. Files are in [`mascot/`](mascot/), and the Figma file has them on the "Mascot" page. Overview: [mascot-overview.png](mascot/mascot-overview.png).

| File | Use |
|---|---|
| `debye-mascot-whatsapp-1024.png` | WhatsApp Business profile picture: 1024 square, cream background, safe inside the circle crop |
| `debye-mascot.png` | Main character, 1024 square, transparent |
| `debye-mascot-fullbody.png` | Full body, 1024×1536 portrait, transparent: pitch slide, staff empty state |
| `debye-mascot-waving.png` | Waving hello: onboarding, first message, empty inbox |
| `debye-mascot-thumbs-up.png` | Thumbs-up "repair done": case closed / completed states |
| `debye-mascot-thinking.png` | Thinking: loading and "Debye is working on it" states |

Generated with the OpenAI Images API (`gpt-image-1.5`, because `gpt-image-1` is not offered in the EU region). The poses were made as edits of the chosen master so the character stays consistent. The simple "d" disc (`debye-avatar.svg`) stays the small UI icon; the mascot is for bigger moments.
