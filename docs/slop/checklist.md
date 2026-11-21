# AI-slop UI checklist

What "AI-generated / vibe-coded" UI looks like, and how to grep for it. Used by the Detector (`report.md`) and the Remover/Replacer.

**Sources** (keys used in the "Source" column):
- **[DC]** DesignCode, "How to Avoid AI Slop in Vibe-Coded Landing Pages" (youtube M4DNgmI7MIM). Transcript could not be fetched (YouTube returned only page chrome). Only title/channel are confirmed. Its themes are taken from write-ups of the same advice: [Aura lesson](https://aura.build/learn/avoid-ai-slop-vibe-coded-landing-pages), [ice-ice-bear summary](https://ice-ice-bear.github.io/posts/2026-04-15-vibe-coding-design/): strip before you add, start from references, have a DESIGN.md/brand rules, critique against a list of known tells.
- **[LJ]** languagejones, "How to Detect AI Slop" (ORgKY9AlybA) and **[MW]** Matt Wolfe, "I Built A Tool To Detect AI Video" (-KcHn0QcSb0). Transcripts not obtainable. Both are about detecting AI *content* (text/video), not UI. Used only for the general principle that slop = generic, low-care, "average" output with no specifics.
- **[BAN]** [Anti-AI Slop Ban List](https://github.com/Laith0003/ux-skill/wiki/Anti-AI-slop-ban-list)
- **[925]** [925 Studios, AI Slop Fonts and Gradients](https://www.925studios.co/blog/ai-slop-design-tells)
- **[FOU]** [Fountain Institute, 7 Signs a UI Has Been Vibe Coded](https://www.thefountaininstitute.com/blog/signs-vibe-coded-ui)
- **[IND]** [DEV: Why every AI-built website looks the same, blame Tailwind's indigo-500](https://dev.to/alanwest/why-every-ai-built-website-looks-the-same-blame-tailwinds-indigo-500-3h2p)
- **[PUR]** DEV "AI purple problem", YouWare "Purple prison of AI frontends", uxdesign.cc "Purple" (search results; purple/indigo gradient and emoji-as-icon explanations)
- **[SDS]** capitalandcompute.net "Fix AI slop in web design, tell by tell"; Laith0003 "How to detect AI slop in your design"; pixelslop ai-slop-patterns catalogue

Caveat: all of these are community field guides, not studies. Instagram/YouTube reels could not be reached from here.

| ID | Pattern | One-line description | How to spot it in code | Source |
|---|---|---|---|---|
| S1 | Purple/indigo gradient | Indigo→purple/pink or blue→purple gradient on hero, buttons or text | `from-indigo`, `to-purple`, `via-pink`, `indigo-500`, `violet-`, `fuchsia-`; `linear-gradient(135deg, #667eea, #764ba2)`; any `gradient` | IND, PUR, 925, BAN, FOU |
| S2 | Gradient text headings | Headline filled with a gradient | `bg-clip-text text-transparent`, `-webkit-background-clip: text` | BAN, SDS |
| S3 | Glowing blurred blobs / aurora | Soft blurred colour orbs or radial bloom behind hero or cards | `blur-3xl`, `blur-[`, `rounded-full bg-.*/20 blur`, `radial-gradient` at low opacity, `filter: blur` | FOU, BAN, SDS |
| S4 | Glassmorphism | Translucent panels with backdrop blur | `backdrop-blur`, `backdrop-filter`, `bg-white/10`, `bg-white/5`, `rgba(255,255,255,.1)` | BAN, SDS |
| S5 | Glow shadows / neon | Coloured glow `box-shadow`, neon text-shadow, glow rings | `shadow-[0_0_`, `shadow-indigo`, `shadow-purple`, `text-shadow: 0 0`, `drop-shadow-[` | BAN |
| S6 | Heavy soft shadow on everything | Big blurry drop shadows on flat cards | `shadow-xl`, `shadow-2xl`, `shadow-lg`, `0 20px 60px rgba(0,0,0` | BAN, 925 |
| S7 | Emoji as icons | ✨🚀⚡🔥📊🎯 etc. as bullets, nav or buttons | grep Unicode emoji ranges in `.tsx`; also glyph "icons" like `➤ ✓ ✗ ▶ ✕ ⚠` standing in for an icon set | FOU, PUR, BAN |
| S8 | Sparkle / rocket badges | ✨ or 🚀 next to headings and CTAs, "✨ New" pills | `✨`, `🚀`, `⚡`, "New" pill above hero | BAN, PUR |
| S9 | Mixed icon styles | Line icons, filled icons and emoji together; thin generic line icons in circles | mixed `<Icon>` + emoji + glyph characters in the same file | BAN, 925 |
| S10 | Generic 3-card feature grid | Row of three equal rounded cards: icon, heading, one sentence | `grid-cols-3`, `md:grid-cols-3`, `lg:grid-cols-3`, three identical siblings | 925, BAN, PUR |
| S11 | Everything centred | Hero and sections all `text-center`, stacked | `text-center`, `items-center justify-center`, `mx-auto max-w-` on every section | BAN |
| S12 | Oversized rounded cards everywhere | One big radius on every element, pill + card + input alike | `rounded-2xl`, `rounded-3xl`, `border-radius: 24px` repeated, off-token radii | BAN, 925 |
| S13 | Stat-tile row with big numbers | Row of 3-4 KPI tiles ("10k+ users") | `grid-cols-2 md:grid-cols-4` with big `text-3xl font-bold` + tiny label | BAN, FOU |
| S14 | Cards for every block / nested cards | Everything boxed; card inside card; coloured left-edge tabs; status dots on everything | `border-l-4`, repeated `rounded-xl border p-6`, `<div className="card">` inside `.card` | FOU |
| S15 | Inter-only default type | Inter (or system sans) for body and display, no typographic personality | `fontFamily: Inter`, `family=Inter` in `index.html`, `font-sans` only | 925, BAN, PUR |
| S16 | No type hierarchy | Same weight/size everywhere, or every heading `font-bold` at similar size; uniform 400/500 | repeated `font-bold`/`font-semibold` everywhere; narrow size scale | BAN, DC |
| S17 | Default Tailwind palette, no brand | Raw `blue-500`, `gray-100`, `slate-900`, `emerald-500` | `colors.(blue|gray|slate|indigo|emerald)`, `bg-gray-`, `text-slate-`; or theme not overridden | IND, 925, DC |
| S18 | Off-palette hex literals | Colours hard-coded outside the theme (drift from brand tokens) | `#[0-9A-Fa-f]{6}`, `bg-[#`, `text-[#`, `shadow-[…#` in `.tsx` | DC (brand rules), SDS |
| S19 | Filler marketing verbs | Seamless / Effortless / Empower / Unlock / Leverage / Revolutionize / Supercharge / Elevate / Transform | grep `seamless|effortless|empower|unlock|leverage|revolution|supercharge|elevate|transform|cutting-edge|next-gen` | BAN, 925 |
| S20 | Weightless slogans | "Build faster. Ship smarter." / "Reimagine the future"; welcome-to-our-platform throat-clearing | short parallel two-clause headlines; `Welcome to`, `We are excited` | 925, BAN |
| S21 | Meaningless badges | "AI-powered", "Powered by AI", "Beta", "New" pills that say nothing | `AI-powered`, `AI assistant`, `Powered by`, small pill above hero | BAN, FOU |
| S22 | Fake stats / testimonials / logos | "10,000+ users", "99.9%", "Trusted by leading brands", "Sarah J., CEO", Acme/TechCorp | grep `\d+,?\d*\+`, `Trusted by`, `testimonial`, `Acme`, `John Doe` | BAN |
| S23 | Placeholder / lorem content | lorem ipsum, stock photos, fake names left in | `lorem`, `placeholder.com`, `unsplash`, `John Doe` | BAN |
| S24 | Over-animated hover/scroll | Scale/translate on hover, fade-up on every element, parallax, endless pulse/bounce/spin, 600ms+ on routine actions | `hover:scale-`, `hover:-translate-y`, `animate-bounce`, `animate-pulse`, `animate-ping`, `duration-500/700`, `transition-all`, `framer-motion` whileInView | BAN |
| S25 | Decorative floating shapes / full-bleed abstract images | Shapes or abstract art with no information value | absolutely-positioned `rounded-full` decorations, `<img>` of abstract art | BAN |
| S26 | Equal-weight twin CTAs | "Get Started" + "Learn More" side by side, same weight | two adjacent `btn` of equal style in a hero | BAN, 925 |
| S27 | Dark hero + gradient CTA | Dark navy/black hero with gradient "Get Started" | `bg-slate-900`, `bg-black`, gradient button | 925 |
| S28 | Generic spinners / missing states | Spinner instead of skeleton; no hover/focus/disabled/empty states | `animate-spin`, buttons without `hover:`/`focus-visible`/`disabled:` | BAN |
| S29 | Title Case / ALL CAPS everywhere | Title Case in all copy, uppercase tracking on running text | `uppercase tracking-`, `capitalize` on body text | BAN |
| S30 | Whitespace without hierarchy | Uniform huge section padding; every section the same height and shape | `py-24`/`py-20` repeated on identical sections, `h-screen` heroes | BAN, DC |

## Principle ("what to do instead", from DC and BAN)
Strip first, then add on purpose. Brand tokens in one place, one icon set, real content, and a specific voice. A UI that states what *this* product does for *this* user reads as human-made.
