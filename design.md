# Design — register-id

Visual and interaction record for the citizen portal in `web/`. Every screen uses this system. Do not swap themes per route.

The rendered values live in `web/src/styles.css`. Hex below matches those tokens.

## Genre

A public-service workbench. One task at a time. No marketing hero, no logo wall, no second theme for the desk.

## Theme

AIT light canvas.

| Token | Value | Use |
|---|---|---|
| `--color-paper` | `#ffffff` | Page |
| `--color-paper-2` | `#f7f7f5` | Cards, path tiles, panels |
| `--color-paper-3` | `#eef2ea` | Quiet green wash |
| `--color-ink` | `#494a4b` | Body and titles |
| `--color-ink-3` | `#6d6e6f` | Meta |
| `--color-rule` | `#e4e4e2` | Hairline |
| `--color-accent` | `#3f6433` | Titles, primary buttons, focus, links on hover |
| `--color-accent-ink` | `#ffffff` | Label on a green button |
| `--color-accent-hover` | `#314d28` | Pressed primary |
| `--color-lime` | `#a1be37` | Header band only. A 4px rule under the header. Not a button color |
| `--color-sage` | `#8db37f` | Completed step line |
| `--color-danger` | `#8b3a2f` | Errors only |
| `--color-ok` | `#3f6433` | Passed checks |
| `--color-ok-wash` | `#e7f0df` | Passed sector |
| `--color-stage` | `#494a4b` | Face stage behind the camera |
| `--color-on-stage` | `#ffffff` | Type on the stage |

Corners are 4px. Controls do not use a drop shadow.

## Typography

- Display and the institute name: Metropolis, weights 500 and 700. Roman. No italic display.
- Body, buttons, and fields: Lato, weights 400 and 700.
- UIN, tokens, and other identifiers: platform monospace.
- Display size: `clamp(2.25rem, 4vw, 3.5rem)`.

`@fontsource/fraunces`, `@fontsource/outfit`, and `@fontsource/ibm-plex-mono` are listed in `web/package.json` and are not loaded by the stylesheet. The portal does not render those families.

## Spacing, motion, controls

Spacing is a 4-point scale from `--space-2xs` (4px) through `--space-3xl` (64px).

Motion is opacity and color, 140–180ms, with `--ease-out` for reveals. `prefers-reduced-motion` removes transform and color transitions.

- Primary: green fill, white label, 4px radius, one main action in a task.
- Secondary: grey outline.
- Quiet: text button for copy, cancel, and dismiss.
- Copying an identifier switches the button to "Copied". No toast.

## Chrome

The header is a white bar with the AIT name, a short rule, and the `register-id` wordmark. The portal nav sits on the right: Enroll, Prove, My ID, Desk. On a narrow screen the header stacks and the nav wraps. The lime band is the only color in the chrome.

`Frame` is the page shell. Citizen steps keep the progress rail. Help and other interruptions use the same shell without the rail. Desk and activity pass `wide` so the column can grow to `76rem`. Below 900px the wide frame becomes a single column and the home path tiles stack.

## Citizen paths

The home screen is two tiles, not one pair of buttons.

- Create an ID. Consent, details, face check, camera, photo, review. About three minutes, a camera, and an email.
- Use an existing ID. Prove the number already issued, with a face check.

The review step no longer asks the browser to invent a UIN or draw the card before enrolment. The server allocates the number. The card on the success screen uses that number. Gender and date of birth are required with the name, email, and scan. A failed challenge, a refused camera, a weak camera, or a failed enrol is reported as an attempt so the desk can see why someone stopped.

After a successful enrol or prove, the session keeps an activity token. My ID, the verified screen, and the unmatched screen link to My activity when that token exists.

## My activity (`/id/activity`)

This is the citizen's own check log for the browser session. Without a token the page asks them to prove the ID first.

With a token it shows the UIN, a status (Active, or Visit the office when an officer has to look), counts for checks, tries used out of 3, and reports. Each row is Created, Passed, Failed, or Reported, with the time and device. The latest face check that has not been disputed can be sent to an officer with a short note. The empty state says a face check will show up here.

## Desk (`/desk`)

Same visual system, full width. Staff sign in with a desk token kept in `sessionStorage`. An unrecognized token clears the session and says it was not recognized.

Officers and custodians can open a person and must give a reason of at least three characters before a write:

- Correct name and email.
- Turn login on or off.
- Lock or unlock the ID.
- Remove a saved face.

The same page has the activity log for one person, the queue of citizen reports (open, then mark checked), the staff list, and all checks. Admins and custodians add or remove staff and change roles. Officers do not manage staff. A newly issued staff token is shown once so it can be copied.

## Lab page

`src/project/web/templates/index.html` is the fallback page when the built portal is absent. It no longer fetches a UIN, invents a number, or posts one. The number field is filled from the enrol response.
