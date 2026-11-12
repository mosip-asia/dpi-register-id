# register-id branding kit

Reference kit for future interface work. Nothing in this folder is wired into the web app.

The institute identity stays official. This kit records how **register-id** (Citizen Registration Gateway) sits beside it. Logo files are not stored here. Obtain them from the [AIT branding downloads](https://ait.ac.th/branding/) or the Office of Public Affairs, and follow the [logo manual (December 2023)](https://ait.ac.th/wp-content/uploads/2024/09/ait-logo-manual-dec2023.pdf).

| Source | URL |
|---|---|
| Institute site | https://ait.ac.th/ |
| Brand guidelines | https://ait.ac.th/brand-guidelines/ |
| Visual identity | https://ait.ac.th/visual-identity/ |
| Logo guidelines | https://ait.ac.th/logo-guidelines/ |

Open `specimen.html` in a browser to see the palette, type, and lockup. Machine-readable values live in `tokens.json` and `tokens.css`.

## Position

register-id is the browser onboarding gateway for citizen and student enrollment. It is an AIT product surface, so the page should read as the institute first and the product second.

| | |
|---|---|
| Motto | Social Impact with Innovation |
| Brand image | Sustainability |
| Product name | register-id |
| Descriptor | Citizen Registration Gateway |

Voice is plain and institutional. Say what the screen does. Keep sentences short. Leave slogans to the institute motto. Photography, when it appears, should be campus and landscape — the gate, trees, Pathum Thani light — in the same spirit as the public site. Skip stock offices, neon dashboards, and invented crests.

## Logo

AIT has two approved marks:

- **Primary:** globe, the letters AIT, and the words Asian Institute of Technology.
- **Secondary:** the globe alone.

Use the green version on light backgrounds. Use the white version on dark backgrounds and on photography that stays quiet behind the mark. Grayscale is for print constraints. The mark is reproduced whole, in proportion, and only in the approved color versions.

Clear space on every side equals the width of the capital **A** in the primary logo. Minimum sizes from the manual:

| Use | Minimum |
|---|---|
| Primary logo, screen | 150 px wide |
| Primary logo, print | 40 mm wide |
| Sub-brand logo, screen | 50 px wide |
| Sub-brand logo, print | 15 mm wide |
| Favicon | 32 px |

Do not separate the globe from the wordmark, redraw it, recolor it, rotate it, squeeze it, or place it inside another shape.

### Product lockup

The product name is type, not a second logo.

```
[ official AIT primary logo ]

register-id
Citizen Registration Gateway
```

On a wide header, place the official logo, a clear-space gap, a 1 px grey rule, then the name. Set **register-id** in Metropolis Bold, AIT Green or Dark Grey. Set the descriptor in Lato Regular, Dark Grey. The institute logo stays at least as prominent as the product name.

## Color

Signature palette, quoted from the visual identity page.

| Name | Hex | Use |
|---|---|---|
| AIT Green | `#3F6433` | Primary identifier. Headlines, green logo, primary buttons. Present on every branded surface. It does not have to dominate the page. |
| Lime Green | `#A1BE37` | One point of emphasis: a band, a large heading, or a short highlight. |
| Sage Green | `#8DB37F` | Large decorative type or a quiet filled area. |
| Dark Grey | `#494A4B` | Body copy and secondary chrome. |
| Light Grey | `#B6B6B6` | Rules and disabled fills. |

Contrast against white, checked for WCAG 2.1:

| Pair | Ratio | Small text |
|---|---|---|
| AIT Green on white | 6.81 | Pass |
| Dark Grey on white | 8.88 | Pass |
| White on AIT Green | 6.81 | Pass |
| Lime on white | 2.11 | Fail. Do not set body or labels in lime on white. |
| Sage on white | 2.36 | Fail. Same rule as lime. |
| Light Grey on white | 2.03 | Fail. Decorative only. |

Lime as a background needs dark ink. `#24321E` on `#A1BE37` is 6.41. Dark Grey on lime is 4.20, which is only enough for large type.

Screen neutrals below are for layout. They are not signature colors.

| Token | Hex | Use |
|---|---|---|
| Canvas | `#FFFFFF` | Page background |
| Paper | `#F7F7F5` | Grouped sections |
| Line | `#E4E4E2` | Dividers and field borders |
| Danger | `#8B3A2F` | Form errors only. 7.65 on white. |

One lime moment per view. Primary actions are AIT Green with white labels. Secondary actions are white with a Dark Grey or AIT Green border. Corners stay at 4 px. The logo is never clipped into a circle or a pill.

## Type

Official faces, from the visual identity page:

| Role | Family | Weights | Use |
|---|---|---|---|
| Display | Metropolis | Medium, Bold, Black | Product name, titles |
| Text | Lato | Light, Regular, Bold, Black | Body, labels, buttons |
| Signature | Arial | Regular | Email signatures only. Black or grey. |

A monospace face is allowed for a UIN or other fixed identifier. It is a product exception, not an institute brand font. Use the platform monospace stack in `tokens.css`.

Suggested scale for the future UI:

| Style | Face | Size | Line height |
|---|---|---|---|
| Title | Metropolis Bold | 40 px | 1.15 |
| Section | Metropolis Medium | 24 px | 1.25 |
| Body | Lato Regular | 16 px | 1.5 |
| Label | Lato Bold | 13 px | 1.3 |
| Identifier | Monospace | 16 px | 1.4 |

## Files

| File | Purpose |
|---|---|
| `README.md` | This kit |
| `tokens.json` | Values for a future build |
| `tokens.css` | Custom properties, not imported by the app |
| `specimen.html` | Static board. Open the file locally. |

When UI work starts, import `tokens.css` and place the official logo file from OPA. Until then, leave `src/project/web/templates/` on its current styles.
