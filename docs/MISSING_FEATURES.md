# Known gaps and uncertain Monta behavior

Version 0.2 restores the useful OCEAN feature set and adds Monta-only state and
controls. The following gaps remain.

For the complete captured app/API inventory and implementation status, see
[ON app feature matrix](APP_FEATURE_MATRIX.md).

## API stability

* ON app login, team-card discovery, charger detail, account-credit controls,
  cable release and receipts use an undocumented private API. Monta can change
  these routes, headers or payloads without notice.
* The captured app reauthenticated with email/password. No refresh-token route
  was observed. The integration restores the persisted bearer session across
  restarts, but must log in again with the same device UUID after genuine token
  expiry instead of guessing a refresh contract.
* Monta's documented Public API credentials cannot access this account's
  assigned charge points. Moving the production path to that API is therefore
  not currently possible.
* Polling is used because no signed-in app webhook or push contract was found.
  Firebase/APNs push delivery is intentionally not reproduced. Asynchronous
  command failures are instead read from charge detail on the next control
  confirmation or normal poll.

## Data not yet proven

* Per-phase current, per-phase voltage and vehicle state of charge are
  implemented as disabled-by-default sensors, but the captured Zaptec session
  returned null values. They will remain unknown unless Monta supplies them.
* A failed start was captured and is mapped even though Monta labels its
  charge record `completed` and stores the actual result in `failed_at` and
  `error`. Scheduled, reserved, charger-suspended and vehicle-suspended paths
  are mapped generically but were not all captured from this installation.
* The physical charger meter is exposed when present, but the app payload may
  omit it and its long-term reset semantics have not been observed.
* Last communication uses Monta's latest measurement/update/connection time.
  Monta does not expose the old OCEAN heartbeat field with identical semantics.
* The signed-in app bearer can read Hub charger detail, so protocol errors,
  firmware status, lifetime counters and integration health are refreshed every
  five minutes. The Hub Control station-log route returns HTTP 403 for this
  account; the integration reports that limitation and does not retry it every
  poll.

## Features intentionally not exposed

* Receipt availability and charge ID are attributes on the last-session cost
  sensor. Home Assistant does not yet provide a receipt download or email
  action because the returned private URL and recipient flow need more testing.
* Smart/scheduled charging preferences, fixed-kWh targets, vehicles,
  subscriptions, wallet transactions and profile editing have API client
  building blocks but no Home Assistant entities. They are not needed for
  charger feature parity and changing billing preferences deserves a separate
  design.
* Operator administration from Monta Hub, including reboot, firmware,
  maintenance mode and charging profiles, is deliberately excluded. Those are
  building-management operations rather than driver controls.
* A config entry represents one selected charger. Configure the integration
  more than once to add multiple chargers from the same ON account.
