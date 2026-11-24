# Host name — `register.<domain>`

## Previous

Examples and the local environment used `register.id.<domain>` or `register.id.ait.ac.th`. The README and the objectives drew eSignet and Inji as the required login and wallet step after enrolment. The project description said `(register.id)`.

## Expected

The Sandbox Kit routes one label under the environment domain. The public host is `register.<domain>`, not `register.id.<domain>`. eSignet and Inji are not part of this enrolment path.

## Now

Helm publishes `register.<domain>` (`hostname: register` plus the environment domain) and records it on the Service annotation `register-id.mosip.io/host`. CI checks `register.sandbox.example.net`. `.env.example` sets `APP_HOSTNAME_DOMAIN=register.ait.ac.th` and says `register.id.<domain>` is the name the Kit does not route. Enrolment writes IDRepo. The password is a separate credential call. eSignet and Inji are named only as products this path does not call. `pyproject.toml` describes the project as `register.<domain>`.

## What was done

Operational host examples were rewritten. The local `.env` hostname was updated to `register.ait.ac.th`. Diagrams and milestone text that required eSignet or Inji after enrol were corrected. The chart comment rejects `register.id.<domain>`.
