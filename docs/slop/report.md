# AI-slop detection report: Debye frontend

Branch `balint-sandbox`. Checklist: [checklist.md](checklist.md) (patterns S1 to S30). Nothing in the code was changed.

**Overall read:** the frontend is already far from the classic slop look (wine palette on warm off-white, hairline-ring cards, pill buttons, no gradients, no blobs, no glass, specific product copy). What is left is mostly (a) glyph/emoji pseudo-icons next to an existing line-icon set, (b) off-token colours and a few gradient/blur remnants, (c) Inter-as-the-only-face, (d) a few generic copy lines, (e) centred hero and big-radius tenant portal, (f) stat-tile rows. Findings are therefore mostly low/med; the high ones are few.

## Files scanned
Config/entry: `frontend/index.html`, `frontend/tailwind.config.ts`, `frontend/src/theme.ts`, `frontend/src/index.css`, `frontend/src/main.tsx`, `frontend/src/tenant/tenant.css`.
Tenant: `tenant/{TenantApp,Login,Home,Chat,shell,progress,api}.ts(x)`.
Components: `components/{Layout,ui,icons,DemoControls}.tsx`, `components/case/{CasePanels,Diagnosis}.tsx`, `components/staff/{CaseFlow,StaffBits}.tsx`.
Pages: `pages/{StaffInbox,StaffCases,StaffCase,StaffUnit,StaffPartners,PartnerInbox,PartnerJoin,PartnerJob,TechPage}.tsx`, `pages/partner/{Portal,Welcome,JobCards,shared}.tsx`.
Lib/api (strings, copy, no UI classes): `lib/{de,de-partner,i18n,format,kb,lifecycle,stage,stream,errors,keys,liveCase,staffBoard,useResource,useNewKeys}.ts`, `api/{mock,types,client}.ts`. Greps for gradient/blur/emoji/hex/copy-phrases/animation/grid/centre ran over all of `src/**`; the copy keys in `lib/de.ts` were scanned for marketing phrasing (none of S19/S22/S23 found). `public/brand/*` and `public/mascot/*` and `public/demo-media/*` checked by name and by usage.

Greps for S1/S2/S3/S5/S6/S19/S22/S23/S25/S27: **no hits** (no `indigo|purple|violet|pink` classes, no `bg-clip-text`, no `blur-*`, no `shadow-xl/2xl`, no "seamless/effortless/empower/unlock/revolutionize", no fake stats, no lorem, no sparkle/rocket emoji). Tailwind `colors` are fully overridden by `theme.ts` (S17 clear).

## Findings

Legend: sev = high/med/low. Action: REMOVE (pure decoration), REPLACE (needs a deliberate alternative), KEEP.

| ID | file:line | pattern | what it is | sev | action | replacement direction |
|---|---|---|---|---|---|---|
| F1 | `pages/partner/Welcome.tsx:23,26,29` | S7, S9 | Emoji as list icons: `🔧 <span>…Jobs that fit you.`, `📸 …Everything up front.`, `💶 …Paid in 14 days.` | high | REPLACE | `<Icon>` from `components/icons.tsx` (wrench, camera, + add a euro/clock path) in wine on `wine-tint` square, or drop icons and use a plain definition list with bold lead-ins |
| F2 | `tenant/Chat.tsx:214` | S7 | `📷 {t('Upload photo')}` in a chip | med | REPLACE | `<Icon name="camera" className="h-4 w-4" />` + label |
| F3 | `tenant/Chat.tsx:265` | S7 | `📎` as attach button glyph | med | REPLACE | `<Icon name="file">`/new paperclip path, 18px, `text-muted` |
| F4 | `tenant/Chat.tsx:294`, `tenant/Home.tsx:99` | S7 | `➤` as send button glyph | med | REPLACE | `<Icon name="arrow">` (already in icons.tsx) inside `.sendc` |
| F5 | `tenant/Chat.tsx:318,413` | S7 | `📎 {kind}` and `📄 {d.filename}` attachment labels | med | REPLACE | `<Icon name="file">` / `mic` + text |
| F6 | `pages/partner/JobCards.tsx:288,415` | S7 | `📷 {photo ? photo.name : t('Add photo')}` / `📷 {file ? …Upload invoice photo / PDF}` | med | REPLACE | `<Icon name="camera">` / `upload` |
| F7 | `components/staff/StaffBits.tsx:100,118` | S7 | Emoji prefix in message preview text: `` `📷 ${t('Photo')}` ``, `` `🎤 ${t('Voice note')}` `` | med | REPLACE | Render preview as JSX with `<Icon name="camera"/"mic">` (change the helper to return ReactNode) or text-only "Photo", "Voice note" |
| F8 | `pages/partner/JobCards.tsx:448,449` | S7 | `` `✓ ${…}` `` and `` `⚠ ${…}` `` status text prefixes | low | REPLACE | `<Icon name="check">` in `text-ok`; for the warning use a `warn`-tinted line with a small alert icon (add path) instead of `⚠` |
| F9 | `pages/partner/JobCards.tsx:74,266`, `pages/partner/Welcome.tsx:379,750`, `pages/partner/shared.tsx:296`, `components/staff/CaseFlow.tsx:173,296`, `tenant/Chat.tsx:363`, `pages/StaffPartners.tsx:129`, `pages/partner/Portal.tsx:124,188` | S7, S9 | `✓` / `✗` glyphs used as check icons (`'✓ '`, `{ok ? '✓' : '✗'}`, `✓ {t('Verified')}`) | low | REPLACE | One shared `<Icon name="check">` (+ a `close` path), stroke 2, sized to the circle; makes the check style consistent with `icons.tsx` |
| F10 | `pages/partner/shared.tsx:263`, `pages/partner/JobCards.tsx:274` | S9 | `›` typed character as disclosure chevron | low | REPLACE | `<Icon name="chevron">` with `group-open:rotate-90` |
| F11 | `components/DemoControls.tsx:53,55,69` and `:77` | S7 | `✓`, `✗`, `✕`, `▶` glyphs in the demo panel | low | KEEP | Demo-only, not customer-facing. Optional: `Icon check/close` for consistency |
| F12 | `pages/partner/shared.tsx:160` | S1/S3 remnant | `bg-[linear-gradient(160deg,#E3E3E8,#C9C9CF)]` cool-grey gradient as photo placeholder | med | REPLACE | Solid `bg-beige-d` (or `photo-bg` token) with a hairline ring; no gradient |
| F13 | `pages/partner/shared.tsx:164,165,168` | S18, S6 | Fake boiler illustration with literal hexes (`#F4F2EE`, `#5E6B60`, `#9FB7A4`, `#1E2A21`, `#FAFAFA→#A9ADB3` radial gradient) and `shadow-[0_6px_14px_rgba(0,0,0,.16/.18)]` | med | REPLACE | Use the existing `photo-bg`/`photo-display` tokens (already in `theme.ts`, `#2B1018`/`#A9C49A`) for the display; drop the radial-gradient blob placeholder in favour of a flat `beige-d` tile with the boiler `Icon` or the real `public/demo-media/boiler_display_F28.jpg` |
| F14 | `pages/partner/shared.tsx:325` | S4, S24 | Toast: `bg-[rgba(29,29,31,.88)] … text-white backdrop-blur transition-all duration-200` with translate slide | med | REPLACE | Solid `bg-ink text-cream rounded-tile shadow-pop`, no `backdrop-blur`; opacity-only fade (`transition-opacity`). `#1D1D1F` is Apple grey, off-palette |
| F15 | `pages/partner/Portal.tsx:423,441,457,461` | S18 | `#F3EEE7` ×4 and two `repeating-linear-gradient(45deg,…)` hatch patterns for the availability grid | low | REPLACE | Add one token (e.g. `beige-l`) or reuse `beige`; hatching is functional ("unavailable") so keep the *meaning* (disabled cell) via `bg-beige-d/50 text-muted line-through` instead of gradients |
| F16 | `pages/partner/Welcome.tsx:748` | S18 | `border-[#D1D1D6]` (Apple grey) | low | REPLACE | `border-beige-d` |
| F17 | `pages/StaffInbox.tsx:74` | S18 | `bg-[#B9AAA4]` avatar colour | low | REPLACE | `bg-muted` token or `bg-beige-d text-secondary` |
| F18 | `tenant/tenant.css:52,115` | S18 | `#C9B9A6`, and `#1E7A35`/`#E6F4EA` hard-coded, though `wa-text`/`wa-tint` exist | low | REPLACE | Use `var(--…)` tokens; add `--wa-text/--wa-tint` to `:root` in `index.css` if needed |
| F19 | `components/staff/CaseFlow.tsx:293`, `tenant/tenant.css:153` | S5 | Halo ring on the current step: `shadow-[0_0_0_5px_#F5EBED]` / `box-shadow: 0 0 0 5px var(--wine-tint)` | low | KEEP | Flat tint ring, not a glow; it is the "current station" marker. Only swap the literal `#F5EBED` for a token |
| F20 | `text-white` / `#fff` on coloured fills: `CaseFlow.tsx:173,293`, `Welcome.tsx:748`, `shared.tsx:296`, `JobCards.tsx:195,343,364,424`, `tenant.css:152,153` | S18 | Pure white text instead of the `cream` token used elsewhere | low | REPLACE | `text-cream` / `var(--cream)` (mechanical swap) |
| F21 | `pages/partner/JobCards.tsx:195,343,364,424` | S14 | Four ad-hoc `btn bg-ok text-white hover:bg-ok/90` buttons, while `index.css` already defines `.btn-success` (aliased to primary) | low | REPLACE | One `.btn-success` defined as `bg-ok text-cream hover:bg-ok/90` and use it; removes "three different button styles" |
| F22 | `index.html:10`, `theme.ts` `fonts.sans` | S15 | Inter is the only loaded face for body and display; headings differ only by weight | high | REPLACE | Pick a deliberate pairing that suits the warm wine brand: e.g. a humanist or grotesk display face for headings (self-hosted, weights 600/700) + keep a neutral text face; set `fonts.display` in `theme.ts`, apply to `h1-h4`, `.text-page/.title/.head`. Remove the Google Fonts hit |
| F23 | `tenant/tenant.css:5,6` | S15 | Tenant portal uses `-apple-system … "SF Pro"` stack, Inter as fallback, so staff/partner and tenant use different faces | med | REPLACE | Use the same family tokens as the rest (single source of truth in `theme.ts`) |
| F24 | `theme.ts` `fontSize` (page 30 / stat 26 / title 24 / head 20 / panel 16 / body 14 …) and `index.css:15` | S16 | Near-uniform scale; `h1-h4` all `font-semibold`; most headings `font-bold` at 24-34px | low | REPLACE | Widen contrast between page title and body (larger display size, lighter body weight, `text-muted` meta), once F22 lands |
| F25 | `tenant/Home.tsx:73-79`, `tenant/tenant.css:~91-96 .hello` | S11 | Centred hero: logo, "Good morning, X." h1, subline, huge input stacked and centred | med | REPLACE | Left-align greeting block with the input under it; keep the logo in the top bar only (it is already there). Drop the extra 52px logo above the greeting |
| F26 | `tenant/Login.tsx:37-39`, `tenant.css:19-21` | S11 | Centred login box with 64px logo, "Log in to Debye", tagline "Your home, your repairs, one place." | low | REPLACE | Left-aligned form, logo smaller, specific tagline ("Check where your repair stands") or none |
| F27 | `tenant/Home.tsx:78`, `Login.tsx:39` | S20 | Soft taglines: "Your home, your repairs, one place." | low | REPLACE | Say what it does: e.g. "Report a problem and follow the repair." |
| F28 | `pages/partner/Welcome.tsx:20` | S19/S22 | Headline "Get repair jobs from thousands of rented homes. No sales, no paperwork." : "thousands" is an unverifiable scale claim (hackathon), tricolon slogan style | med | REPLACE | Factual: "Repair jobs from reltix properties, with diagnosis, photos and budget attached." (matches the Lead on line ~69) |
| F29 | `pages/partner/Welcome.tsx:68-69` | S20 | `H2 Welcome` over a lead sentence, plus an eyebrow "Debye partner portal"; Welcome-style throat-clearing | low | REPLACE | Drop "Welcome", make the H2 the value statement; eyebrow can stay |
| F30 | `tenant/Home.tsx:97` | S20 | Hint "I already know your address and your appliances." | low | KEEP | Specific and functional (real product behaviour) |
| F31 | `index.html:7` | S21 | `<title>Debye · AI assistant</title>`: "AI assistant" label as identity | med | REPLACE | `Debye · Repair status` / `Debye · Heating repairs`; no "AI" badge |
| F32 | `tenant/tenant.css:79,132` | S12, S6 | `.bigin` and `.cin` use `border-radius: 24px` plus `0 6px 24px / 0 4px 16px` soft shadows; 12px on inputs/buttons (`:24,26,67`), 18px bubbles (`:107,110`), 14/16px cards | med | REPLACE | Use the `theme.ts` radii only (`panel 16`, `tile 14`, `DEFAULT 10`, `chip pill`); inputs 10px, composer 16px; drop the soft drop-shadow on the composer, keep the hairline ring |
| F33 | `components/staff/CaseFlow.tsx:40` and `theme.ts` `shadow.lift` | S6 | Wine-tinted `0 8px 28px` lift shadow on the approval panel | low | REPLACE | `shadow-card` + 1.5px wine ring (`shadow-rec`) to mark "needs you"; no big blur |
| F34 | `pages/partner/Portal.tsx:126-131`, `pages/StaffUnit.tsx:135-146`, `pages/StaffPartners.tsx:135-146` | S13, S10 | Four-up KPI tiles (`grid-cols-2 lg:grid-cols-4`, big `text-page/stat font-bold` + small label). StaffUnit/StaffPartners duplicate the same `.map` block | med | REPLACE | Real data, so keep the numbers; present as one inline "summary strip" (one row, dividers, no individual tiles) or a `dl` in the header. Share one component to remove the duplicated markup. Portal `Kpi` buttons are navigation, so keep their click targets |
| F35 | `pages/partner/Portal.tsx:241` | S24 | `hover:-translate-y-px transition-transform` on KPI tile | low | REMOVE | Hover state by `hover:bg-beige/40` only |
| F36 | `pages/partner/Portal.tsx:187-190` | S7, S14 | "All caught up" empty state: green circle with `✓` + bold + muted line, centred | low | REPLACE | Plain muted sentence ("No new jobs, requests or missing invoices.") left-aligned, with the check as an `Icon` |
| F37 | `components/Layout.tsx:51`, `components/case/CasePanels.tsx:168` | S24, S28 | Two `animate-pulse-dot` (infinite) on the "Live" indicators | low | KEEP | Functional (connection state). CasePanels:168 duplicates Layout's LiveDot; optional: reuse `<LiveDot/>` |
| F38 | `components/case/CasePanels.tsx:56` | S24 | `transition-colors duration-700` on lifecycle track | low | REPLACE | `duration-200`; slow on a state change |
| F39 | `index.css:61-69,71-73` | S24 | `animate-enter` (1.6s background flash + 8px slide), `animate-rise`, `animate-station` (0.6s) | low | KEEP | Authored, tied to real events (new activity, step done). Optional: trim `enter` to 0.8s |
| F40 | `components/staff/CaseFlow.tsx:46-50` | S10 | `lg:grid-cols-3` ranked partner cards | low | KEEP | Functional comparison of three ranked partners; the "Recommended" card is already visually distinct |
| F41 | `pages/PartnerJob.tsx:342` | S10 | `grid-cols-3` of time-window buttons (mobile slot picker) | low | KEEP | Functional picker, not a feature grid |
| F42 | `pages/partner/Portal.tsx:139`, `components/Layout.tsx:67` | S29 | `uppercase tracking-[.04em]` weekday label and `uppercase` EN/DE toggle | low | KEEP | Short labels only, not running text |
| F43 | `tenant/tenant.css:107-111` | S12 | Asymmetric chat bubbles `4px 18px 18px 18px` | low | KEEP | Standard chat convention, keep (tie 18px to a token if F32 is done) |
| F44 | `public/brand/*`, `public/mascot/*`, `components/ui.tsx:95-108` (`Mascot`) | brand | Debye logo / avatar / mascot poses; `Mascot` maps every pose except `avatar` to the logo; `ActorIcon` uses the avatar for Debye | n/a | KEEP | Brand assets, used correctly. Note: `public/mascot/{waving,thumbs-up,thinking}.png` are no longer referenced by `Mascot` (it maps to the logo); leave them |
| F45 | `public/demo-media/*` | brand/demo | Boiler display, repair photo, invoice PDF | n/a | KEEP | Demo-critical; use `boiler_display_F28.jpg` instead of the fake illustration in F13 where possible |
| F46 | `api/mock.ts:393` | S7 | `'👍 Ja, warm!'` in mock tenant message | n/a | KEEP | Realistic WhatsApp reply in fixture data, not UI chrome |
| F47 | `tailwind.config.ts`, `theme.ts` palette | S17 | Brand palette fully custom (wine/beige/ok/warn/red/blue), default Tailwind colours removed | n/a | KEEP | This is the main anti-slop asset; do not reintroduce `slate/indigo` etc. |
| F48 | Chat, case progress (`progress.ts`, `Chat.tsx` flow list, `CasePanels` lifecycle), `DemoControls` | n/a | Functional/demo-critical flows | n/a | KEEP | Only appearance flagged (F2-F9, F32); structure untouched |

## Counts
Total 48 rows. REPLACE: 33 (F1-F10, F12-F18, F20-F29, F31-F34, F36, F38). REMOVE: 1 (F35). KEEP: 14 (F11, F19, F30, F37, F39-F48; F44-F48 are brand/demo-critical). Severity of the 34 actionable rows: high 2 (F1, F22), med 15, low 17.

## Top 5 biggest offenders
1. **Emoji / glyph pseudo-icons** (F1-F10): `🔧📸💶` on the partner welcome, `📷📎📄➤` in tenant chat and partner job cards, `🎤📷` in inbox previews, `✓ ✗ ⚠ ›` typed as icons, while `components/icons.tsx` already has the line-icon set. Single biggest tell, easy to fix.
2. **Inter as the only typeface** (F22, F23, F24): no typographic identity; the tenant portal uses a different stack from staff/partner.
3. **Centred, large-radius tenant hero and composer** (F25, F26, F32): stacked centred logo + greeting + 24px pill input with soft shadow, off the token radii.
4. **Off-palette and glass/gradient remnants** (F12-F18, F20): grey photo-placeholder gradient, fake boiler illustration with literal hexes, blurred translucent toast (`backdrop-blur`, `#1D1D1F`), `#F3EEE7`/`#D1D1D6`/`#B9AAA4`, `text-white`.
5. **Generic copy lines + "AI assistant" title** (F27-F29, F31): "thousands of rented homes. No sales, no paperwork.", "Welcome", "Your home, your repairs, one place.", `<title>Debye · AI assistant`.
(Runner-up: KPI stat-tile rows, F34.)

## Design tokens currently available (for the Replacer)

**`src/theme.ts` colours (v3 base):** `bg #FAF8F5`, `surface #FDFCFA`, `ink #2B1018`, `secondary #5A4744`, `muted #8E807A`, `line rgba(74,20,36,.10)`, `wine #6B1F33`, `wine-d #571828`, `wine-tint #F5EBED`, `beige #EFE8DF`, `beige-d #E2D8CB`, `ok #2F7D4F`, `ok-tint #E7F3EB`, `ok-line #BFDCC9`, `warn #B04A12`, `warn-tint #FBEDE3`, `red #C0262D`, `red-tint #FCE9EA`, `blue #34508C`, `blue-tint #E9EEF8`, `cream #FDFAF7`, `chat-bg #EFEAE2`, `chat-out #D9FDD3`, `wa-tint #E6F4EA`, `wa-text #1E7A35`.
**Aliases:** `rail` (=ink), `rail-active` (wine-tint), `rail-text` (secondary), `rail-text-active` (cream), `sub` (beige), `on-action` (cream), `action` (wine), `action-soft` (wine-tint), `action-dark` (wine-d), `positive/-soft` (ok), `negative/-soft` (red), `warning/-soft` (warn), `life-done` (ok), `life-current` (wine), `life-upcoming`/`life-track` (beige-d), `photo-bg #2B1018`, `photo-display #A9C49A`. `chipColors`: positive, negative, warning, action, blue, neutral.
**Fonts:** `sans` Inter + system stack; `mono` ui-monospace stack. No display face.
**Font sizes (px, rem-converted):** page 30/36, stat 26/32, title 24/30, head 20/26, panel 16/22, body 14/21, body-sm 13.5/20, label 13/19, meta 12/17, tiny 11/15; negative letter-spacing on headings.
**Radius:** none 0, chip 980px, sm 6, DEFAULT 10, tile 14, panel 16, full 9999.
**Shadow:** none, card (1px hairline + 1px/3px), ring (1px hairline), lift (hairline + 8/28 wine-tint), rec (2px wine ring + 6/18), bubble, pop (8/24).
**Spacing (extend):** rail 72px, header 57px, work 28px, inspector 400px, conversation 380px, row 64px.
**Motion:** easing `cubic-bezier(0.16,1,0.3,1)`, hover 140ms (declared in `theme.ts`, not wired into tailwind config).
**`tailwind.config.ts`:** `theme.colors` replaced by `transparent/current` + theme colours (no default palette), `fontFamily`, `fontSize` (rem), `borderRadius`, `boxShadow`, `extend.spacing`. `content: index.html, src/**/*.{ts,tsx}`. No plugins.
**CSS variables (`index.css :root`, used by `tenant.css`):** `--bg --surface --ink --body --muted --line --wine --wine-d --wine-tint --beige --beige-d --ok --ok-tint --ok-line --warn --warn-tint --red --red-tint --blue --blue-tint --cream` (no `--wa-*`).
**Component classes (`index.css`):** `.btn .btn-primary .btn-secondary .btn-ghost .btn-success .btn-inverse .btn-danger .link-btn .label .field .panel .panel-head .card .pill .tab .tab-on .cnt .cnt-soft .uav .crumb table.t dl.kv`.
**Icons (`components/icons.tsx`):** check, arrow, back, chevron, mic, file, camera, shield, phone, calendar, upload, download, cases, building, user, wrench, gear, briefcase, jobs, search (no close, alert, paperclip, euro).
