# Debye v4 polish: audit and plan

Design-polish session, 21 Nov, 03:00–04:00. Live app at :8000, v3 wine design (PRs 101–104).
Skills used: `impeccable` (pbakaus/impeccable: polish, operate mode, craft floor), `unslop-ui`
(heydamir/unslop: the UI slop signs list), `frontend-design` (anthropics/skills), and `unslop`
(asavvin-pixel/unslop, already installed) for copy.

What stays: layout and structure of every page, the wine palette, Inter, the line logo, pill buttons, and the
wording intent. What changes: the craft layer on top.

Screenshots: `before/*.jpg` (live app), `after/*.jpg` (mockups). Mockups: `*.html` (open `index.html`).

## Across the app (do once, every page benefits)

1. **Too many pills.** One row can carry a channel pill, a status pill, a "Needs you" pill and an unread dot,
   and the case header has two pills next to a third in the approval card. Status becomes a 6 px dot plus text
   (`.st`). Only "Needs you" and "Recommended" keep a tint, a single quiet wine one. Channel and trade become plain meta text.
2. **Competing accents.** Wine, green (Accept job button, WhatsApp pill), blue (Booked, Live) and orange
   all carry weight on one screen. Wine becomes the only action colour. Green, orange and blue only mark state, as dots.
3. **Heading weight.** Page titles are 700, card titles a mix of 600 and 700, and labels go as small as
   11 px semibold. New scale: 28/18/15/14/13/12 with weights 400/500/600. Hierarchy comes from size and colour.
4. **The same fact said three times.** On the case page, diagnosis, confidence and cost each appear in the summary, the
   diagnosis card and the progress flow. On partner jobs, the cost cap shows twice in two formats (€240 / €240.00 incl. VAT) and "Approved" appears three times.
   Each fact now has one home.
5. **Developer labels in staff UI.** "Input", "Classifier", "Missing data · Classifier", "Consent · Matching · Approval",
   "0 fields · 14 filled from centrix". These become plain sentences ("Sofia typed nothing by hand. 14 details came from centrix.").
6. **Emoji as icons.** Partner welcome (🔧 📸 💶), call button (📞, which renders pink), tenant send button (➤ glyph).
   They become one line icon set at 16 px with a 1.5 stroke, drawn in text colour.
7. **Greeting headlines.** "Good morning, Luka." (tenant) and "Hi Ali" (tech) become "What's wrong at home, Luka?" and
   "Your jobs, Sun 22 Nov".
8. **States.** Loading is a grey "Loading…" line in an empty page (inbox shows a blank detail pane for 2–5 s).
   Empty is "All caught up." / "No open cases…". 404 is a bare centred line. Plan: skeleton rows for lists, an
   empty state that says what will appear and why, and a 404 that keeps the top bar.
9. **Mixed formats.** Phone numbers show as +490000000011 next to +49 000 •••• 0014. Money shows as €240 / €240.00 / €498.61.
   Times show as 08:00–10:00 / 8–10 / 10:00–12:00. One format each: `+49 000 0000011`, `€240`, `08–10`.
10. **Radii and rings.** Panels use 16, tiles 14, inputs 10, chips 980, cnt badges full. Ladder: control 10, tile 12,
    panel 16, pill only for buttons and chips.

## Per page, ranked by visual impact

### 1. Staff case detail (`/staff/cases/case_0009`), mockup: `staff-case.html`
- The approval moment is three equal cards. The recommended one only differs by a wine ring, and its €263 is the
  only number on the page. Alternatives repeat the same consent sentence in each card.
- Header: two pills (Urgent, Needs approval), then a "Needs you" pill inside the card. Three ways of saying one thing.
- Summary, Diagnosis and Progress repeat "Boiler fault (e.g. F.28 ignition failed)" and 85% three times.
- Progress uses developer tags ("Input", "Classifier") and a dashed list of upcoming steps with tag noise.
- Documents shows `report_case_0001.json` on case 9 (data bug, see below).
- **After:** the recommended partner becomes one wide row (who · why Debye picked them · price + Approve). The alternatives
  become a quiet two-line table with the deciding reason in orange. Consent is said once in the footer. Status
  moves to two dot labels in the header. Summary and Diagnosis merge into one card: the tenant's quote, likely cause, flat, time, Q&A.
  Progress keeps its six stations without the tags.

### 2. Staff inbox (`/staff`), mockup: `staff-inbox.html`
- Rows have up to four badges. The WhatsApp pill wraps to its own line when the name is long, so row heights
  jump (Grace, Aylin, Yusuf rows are taller than Max's).
- Detail summary shows "Diagnosis: Still asking questions" as if it were a value.
- Detail pane is blank while loading.
- **After:** every row is name + time / problem / status dot + last message, all one height. Unread rows get a wine time
  and semibold name, not a dot. Filter tabs get an underline with counts. Summary becomes three facts plus one sentence about where
  Debye is. One primary action ("Review partner") with "Open case" as a text link.

### 3. Partner new job (`/partner/heizung-schmidt/new`), mockup: `partner-new-job.html`
- A grey 3D sphere as the photo placeholder: the clearest AI tell in the app. Also on Work in progress.
- Three pills (Normal, Plumbing, Live). "Live" means nothing on a job card.
- Green "Accept job" button: the only green primary in the app.
- "How we got to the diagnosis" repeats the title, then "Approved". "Show the case history (1 steps)".
- **After:** no photo placeholder. A small "No photos yet" row appears only when there are none. Trade and time go in the meta line,
  plus a "1 h 42 min left to accept" line in orange, because the 2-hour rule is the real pressure. The budget is shown once at top right.
  Q&A from the case evidence. Slots are selectable chips with a check, and Accept is wine.

### 4. Tenant home (`/tenant`), mockup: `tenant-home.html`
- Desktop: a 560 px centred column in a 1440 page. The logo appears twice (top bar + above the greeting).
- "Good morning, Luka." greeting, and the placeholder reads "Please enter your problem, e.g. …".
- ➤ glyph as the send icon. Chips centred under the box.
- **After:** left-aligned ask with the cases list beside it on desktop (stacked on 375 px). The headline asks the question.
  Send is a line arrow. The WhatsApp and call alternatives appear as quiet links. The case card shows the next step with an 8-segment track.

### 5. Partner welcome and register shell (`/partner`, `/partner/register`), mockup: `partner-welcome.html`
- Left panel is a textbook template: bold 700 headline, three emoji feature rows, an unverifiable claim ("thousands of rented homes").
- Right side: a "Debye partner portal" kicker over "Welcome", then two buttons in a large empty area.
- **After:** same split. Line icons replace the emoji, the headline drops to 600 with no "thousands" claim, and the
  right side shows what a partner actually gets: a real job card (cause, boiler, slot, approved budget).

### 6. Call page (`/call`)
- Everything centred in a card inside a page. 📞 emoji in the button (renders pink). "AI assistant by reltix · same case as on WhatsApp".
- Plan: line phone icon, left-aligned on desktop, and the select becomes a labelled field.

### 7. Technician page (`/tech/tech_ali`)
- "Hi Ali" in 40 px bold. One card floating in an empty phone screen.
- Plan: "Your jobs" + date, card with time first (techs plan by time), and an empty state: "No jobs today. New ones appear here when your dispatcher assigns them."

### 8. Staff cases list (`/staff/cases`)
- Problem text sits higher than the Flat/Partner columns (top vs middle alignment). Five different status pill colours.
- Plan: middle-align rows, status dots, and progress dots in ink/wine/beige only.

### 9. Partner WIP and done (`/partner/heizung-schmidt/wip`, `/done`)
- Same sphere placeholder. Tab-style progress strip with a ✓ glyph. "Approved · paid within 14 days" green pill.
- Plan: same treatment as New jobs. Invoice status becomes a dot.

### 10. Unit, partners list, demo panel, `?stage=1`
- Unit: four equal stat tiles (2 / 1 / 0 / €690) are the hero-metric template, and "0 Invoices" is noise. The plan is one line of
  meta, which frees the space for the cases list.
- Partners: fine. "1 active" pills become plain numbers.
- Demo panel and stage: fine. The panel is a utility and stays as it is.

## Data and content bugs found (not design, for the lead)
- Case 9 diagnosis label says "Boiler fault (e.g. F.28 ignition failed)" while the tenant reported F4 and the chat says F4.
- Documents on case 9 and unit_41_1 show `report_case_0001.json` (wrong case, and a raw .json filename for staff).
- "Show the case history (1 steps)" pluralisation.
- `/wip` and `/done` (as listed in the task) are 404. The real routes are `/partner/<pid>/wip` and `/done`.

## Not changing
The structure, routes, brand palette, logo, Inter, EN/DE copy intent, the chat colours (WhatsApp look), demo controls.

## Round 2: skills run properly (21 Nov)

Loaded `impeccable`, `unslop-ui` and `frontend-design` through the Skill tool and worked through their playbooks:
impeccable `polish` + `craft-floor` + operate mode, and unslop-ui's `signs.md`, `tokens.md` and end checklist.
impeccable's launcher (`scripts/impeccable context` / `shot`) was not run because it downloads and executes a separate
program. I followed its documented fallback instead: read the project context directly (no PRODUCT.md or DESIGN.md
exists) and verified each page by rendering it in the browser at 1440 and 375 px.

What the checklists caught in round 1, now fixed:
- Nested cards (approval card inside a panel, chat box inside a panel, photo tile inside the job card). impeccable: "nested cards are always wrong".
- Kickers above headings ("Plumbing · case 7 …", "New job · Heating"). impeccable bans them outright.
- Muted text #8E807A on #FAF8F5 was 3.6:1, below the 4.5:1 floor. Now #7A6C64 (4.8:1). **This is a token change for theme.ts in step 4.**
- Headings at 600. Now 500, with hierarchy from size. 600 is kept only for the one large figure per screen.
- Middle-dot meta strings ("A · B · C"), a frontend-design template tell. Now spacing or plain commas.
- Two time formats on one page (08:00–10:00 and 08–10). Now 08–10 everywhere.
- Browser surfaces left at defaults. Added focus rings, caret colour, scrollbar colour and themed selection.
- No phone layouts for staff and partner pages. Now one column at 375 px with no horizontal scroll (checked with scrollWidth).
- No signature. Added the case track: 8 segments, current station in wine, used on inbox rows, the case header, the job sheet and tenant cards.
- Partner welcome had two competing headlines and a "jobs, not phone calls" construction. Now one headline from the client's copy.
- An entrance animation started at opacity 0, so the approval card stayed invisible wherever animations don't run (the browser pane showed this). It now starts from a visible state and only moves 8 px.
- Missing states. Added states.html: loading skeleton, three empty states, and a not-found page with the top bar.

Round 1 screenshots are kept in `after-round1/`.

## Round 3: "AI usually does X, we do Y" (21 Nov)

Luka asked for Lexend, square-ish corners, and a rule for each AI default. The full list, drawn live with sources, is in `rules.html`.
Changes in `polish.css`: Lexend 300/400/500; radius 2 px tags, 3 px controls, 4 px panels (6 px only for WhatsApp bubbles);
rectangular buttons with a 2 px key edge on the primary, an ink-outline secondary and an underlined-link third level, no pills or arrows;
flat hairline surfaces with one floating shadow per screen; square status markers, avatars and step markers; an underline for
the active nav item; a modular type scale (12/13/14/17/21/26); square focus outline; square line caps on icons.
Caught during this pass: a wine stripe down the selected inbox row, which impeccable bans as a side stripe. Removed.
Round 2 screenshots are in `after-round2/`. For step 4: these are token changes in theme.ts (font, radii, shadows) plus the
button, nav, avatar and status components.

## Round 4: the deeper pass (21 Nov)

Luka said it still looked sloppy. That was fair. Rounds 1–3 used the skills as defect checklists in light-polish mode and
skipped the parts that judge the whole screen. This round ran impeccable's critique the way it's specified: an independent
sub-agent with the rubric (cognitive load, Nielsen 0–4, personas) that never saw my reasoning. I also read unslop-ui's
reference screens and visuals guide, and impeccable's typeset and layout playbooks. impeccable's detector was not run,
because it is a downloaded binary.

What the critique found under the round-3 rules, and the fix:
1. Washed-out type: Lexend 300 at 13 px in grey. Now body text is 15 px/400 and values are ink.
2. Scale too compressed (17 vs 14). Now 36 / 20 / 15 / 12, with one 44 px figure per screen.
3. Three near-identical whites, so panels dissolved. Now a #F2EDE6 paper ground, white sheets and 16% lines.
4. Dead bands (45–55% of some viewports). The tenant page leads with the open case, the partner job uses the full width with a
   sticky decision panel, and the welcome job sheet runs off the edge.
5. The same box with a filler right-hand tag, four times. Diagnosis, Progress and Flat are now ruled sections on the ground; boxes only
   for the decision, the conversation and the composer.
6. The key status was the smallest thing on screen. It is now a 15 px/500 coloured line under every title (`.state`).
7. The case track was illegible. It is now 4 px and always labelled ("Approve partner, step 4 of 8"), and removed from inbox rows.
8. Label-over-value soup. Now label-left/value-right facts and plain sentences ("Viessmann-certified for this boiler, and free…").
9. The product's world was absent. The boiler's display is now drawn (F4 on an LCD, in JetBrains Mono).
10. A grey caption under every heading. About 70% cut; the consent line stays.
11. The four green checks plus "Recommended" pattern. Now one reason sentence in ink.
12. On a phone, Approve sat below the fold. There is now a sticky bottom bar with the price and Approve and send.
Not taken: a wine left stripe on "needs you" rows (impeccable bans side stripes). Those rows use a tint instead.
Round-3 screenshots are in `after-round3/`.

Re-score by a second independent agent after round 4: cognitive load 4 failures (high) to 2 (moderate); aesthetic 2 to 3; real-world
match 2 to 3; staff case "about 60% generic" to "No, the strongest screen"; no AI tells found. Its top six were then fixed:
all three partners in one comparison table with labelled columns and the reason the recommendation beats a higher rating;
selected and "needs you" inbox rows look different; a sticky Accept bar on the phone partner job; the tenant date tile moved to the brand
tint; the welcome job sheet no longer cuts off text; one verb, "Approve partner", everywhere; plausible demo phone number.
Still open (product decisions, not styling): no undo window after approving, no keyboard approve or batch approve, error states
for forms not designed.
