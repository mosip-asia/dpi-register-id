# Design — register-id

A locked design system for the citizen registration portal. Every screen reads
this file before changing the visual layer. The official values live in
`branding/tokens.css`. Do not invent a second palette.

## Genre

modern-minimal, used as a trust-first public service. This is a multi-step
registration wizard, not a marketing site.

## Macrostructure family

- App pages: Workbench. One shell, a progress rail, a single task column, and
  an optional aside. Screens vary by task (form, scan, result), not by theme.
- Enroll rail: Start, Consent, Details, Face check, Camera, Photo, Review, ID.
- Prove rail: Service, Your ID, Face check, Result.
- Help, paused, and fix stay off the rail. They are interruptions.
- Interrupt pages (help, paused): the same shell without a progress rail, so
  the rail does not claim a step the person is not on.

## Theme

Official AIT signature colors. Hex in `branding/tokens.css` is the source of
truth.

- `--color-paper` `#ffffff` (`--rid-canvas`)
- `--color-paper-2` `#f7f7f5` (`--rid-paper`)
- `--color-ink` `#494a4b` (`--ait-grey`)
- `--color-rule` `#e4e4e2` (`--rid-line`)
- `--color-accent` `#3f6433` (`--ait-green`)
- `--color-accent-ink` `#ffffff` (required on the green control; 6.8:1)
- `--color-focus` `#3f6433`
- `--color-danger` `#8b3a2f` (`--rid-danger`, errors only)
- `--ait-lime` `#a1be37` and `--ait-sage` `#8db37f` stay in the signature set.
  They are not a second accent for buttons.

## Typography

- Display: Metropolis, weight 700, roman
- Body: Lato, weight 400
- Identifier: ui-monospace
- Headings stay roman. Emphasis uses weight, not italic.

## Spacing

4-point scale already named `--rid-space-1` through `--rid-space-8`.
Corner radius is 4px on inputs, buttons, panels, and photos.

## Motion

- Easing: `--rid-ease-out` (`cubic-bezier(0.16, 1, 0.3, 1)`)
- Duration: `--rid-dur` (160ms)
- Page enter: opacity only
- Reduced motion: no transform, no color transition

## Microinteractions

- Silent success. Copying an ID switches the button label to "Copied".
- No celebratory toasts.
- Pressed controls move 1px. Focus rings appear instantly.

## CTA voice

- Primary: green fill, 4px radius, one action per screen.
- Secondary: grey outline.
- Quiet: hairline outline for cancel, back, and copy.
- One label per intent. "Create my ID" is only the control that creates the ID.

## What screens share

- The AIT wordmark and register-id lockup.
- Accent green on the current step, primary button, and headings.
- Metropolis + Lato.
- The same button shapes and the workbench frame.

## What screens may differ on

- Whether the progress rail is present.
- Whether the aside is present.
- The task in the center column.

## What this system refuses

- A second theme per route.
- Serif display type.
- Marketing heroes, logo walls, and numbered eyebrows.
- Purple, mesh gradients, and glass panels.
