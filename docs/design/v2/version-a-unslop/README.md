# Version A: unslop

Made by following [unslop](https://github.com/heydamir/unslop) by Damir Sokolovsky (CC BY 4.0): `SKILL.md`, `references/signs.md` and `references/tokens.md`. Figma page: **Version A – unslop**.

PNGs: `staff-case-detail.png`, `staff-cases-list.png`, `partner-job.png`, `whatsapp-flow.png`. Tokens: `tokens.json`.

## Direction (the skill's five lines)

- **Product:** Debye turns a resident's WhatsApp voice note into a booked, invoiced repair, and shows reltix property managers each step.
- **Character:** calm, exact, dependable.
- **World:** the caretaker's office: job tickets, key cabinets, navy work jackets, brass key tags.
- **Moments:** the live timeline, and the invoice landing on the unit as a real paper document.
- **Signature:** case references set as small brass key tags.

## Audit of v1 (signs found)

Purple and lilac everywhere, plus a sparkle on the logo mark. Uppercase tracked labels ("ZERO FORMS", "COST BEARER"). Filled status pills on every row. A hero number ("14") in a dark card. Equal cards side by side. Serif display face on card titles. Many tints of the same hue. Copy with exclamation-style warmth ("Super,…").

## Rules applied, by pass

1. **Spacing:** a 4 px grid; equal padding in sibling cards (24); 40 px nav rows with 4 px gaps; table rows 64.
2. **Colour:** one neutral ramp (the "ink" ramp from the tokens); brand navy `#12294A` is the only accent (primary button, selection, newest event). Semantic green, red and amber only carry status. Hairline borders, small neutral shadows. No gradients or glows.
3. **Icons:** lucide at 18 px, stroke 1.5, in the muted text colour. No emoji.
4. **Copy:** sentence case, no trailing periods on labels, no greetings or hype. "Search" instead of "Search unit, tenant, case". The approval says what Debye is doing ("holding the job until you decide").
5. **Type:** IBM Plex Sans 400/500 for the interface, Plex Mono for IDs, times and money. Hierarchy comes from size and colour, not weight. No uppercase labels, no italics.
6. **Layout:** real app proportions: a 256 px sidebar and fluid content. Sections and order kept: timeline next to WhatsApp, then case and unit, then partner choice and documents.
7. **Details:** nested radii (cards 14, controls 8, tags 6). Status shown as a dot plus text instead of filled pills. Stat cards are numbers only. Ranking uses thin bars, one accent.
8. **Visuals:** no generated images in the app. The moments are drawn from the product: the invoice as a paper sheet, and the boiler display photo.
9. **Motion (spec only):** one easing curve; only the newest timeline item enters (fade and 8 px rise).

## What changed vs v1

- The cream and aubergine theme is gone. Surfaces are now neutral grey and white, and navy appears only where it means something.
- Baskervville is dropped. All type is one sans plus a mono.
- The "14 pre-filled" hero card is now two plain rows in the case facts ("Luka did: 1 voice note, 2 taps", "From centrix: 14 fields filled in").
- The approval card is calm and white instead of filled.
- The Debye mark is the new mascot avatar.
- WhatsApp copy: no exclamation marks, and plainer wording.
