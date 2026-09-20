# Monta API building blocks

The `custom_components/on_is/monta` package contains reusable API clients and
normalized data records. `MontaOnIsClient` adapts the signed-in app client to
the integration's stable coordinator contract. This preserves existing entity
IDs while moving production reads and controls from OCEAN to Monta.

## API surfaces

| Client | Surface | Support level | Current use |
| --- | --- | --- | --- |
| `MontaAppClient` | `api.monta.app` | Private/experimental | ON email/password login, team charger discovery, cable state, account-credit payer selection, live measurements, start/stop, cable release, history and receipts. |
| `MontaPublicClient` | `public-api.monta.com` | Documented | Application auth, charge history, wallet, AFIR, charge-point reads and start/stop when authorized. |
| `MontaPartnerClient` | `partner-api.monta.com` | Documented | Operator charger/session data, telemetry history, statistics, pricing, webhooks and payer-aware start/stop. Requires Partner credentials. |
| `MontaHubClient` | `hub.monta.app/api/...` | Private/experimental | Hub charger detail, EVSE state, sessions, live Control telemetry and explicit user/team start/stop. Read endpoints accept the signed-in app bearer. |
| `MontaDeeplinkClient` | `deeplinks.monta.app` | Private/experimental | Public permanent-link summary and guest-authenticated cable, meter, price and guest-session state. |

Capability and stability metadata lives in `contracts.py`. It lets a future
setup flow describe what a source supports without using class-name checks.

## Shared records

The clients preserve full raw responses and also expose normalized records:

* `ChargerSnapshot` keeps charger state, backend connection, cable state and
  active charge separate. In particular, `available` does not imply that the
  cable is unplugged. Charger `avg_kw` is retained as `average_kw`, not live
  power.
* `ChargeSession` normalizes timestamps, driver price, operator cost, energy,
  SoC, payment method, start/stop/release transitions and stop/failure reasons.
  Signed-in app power comes from `last_measurement.kw_charge_point`.
* `TelemetryMeasurement` normalizes Wh/W API values to kWh/kW while preserving
  current, voltage, phase values and SoC.
* `MontaPage` accepts the offset, cursor and simple-list envelope variants seen
  across Monta APIs.
* `MontaToken` accepts documented camelCase OAuth tokens and the private app
  and guest APIs' snake_case token envelopes.

All normalized entity IDs are strings. Monta charge IDs can exceed JavaScript's
`2^53 - 1` safe-integer limit, and the observed deeplink API rounded the final
digits of an active charge ID. Treat IDs as opaque values and never perform
arithmetic on them.

## Authentication and failures

`MontaOAuthClient` implements client-credential login, refresh-token rotation,
token restoration and one retry after an HTTP 401. The shared transport maps:

* 401 to `MontaAuthError`
* 403 to `MontaAccessError`
* 404 to `MontaNotFoundError`
* 429 to `MontaRateLimitError`, including numeric `Retry-After`

`redact_monta_data()` recursively removes tokens, credentials, cookies, email,
phone and identity-recovery query values before raw payloads enter diagnostics.

`MontaAppClient` logs in with the ON account's email/password and re-authenticates
once after token expiry or HTTP 401. The Android capture did not include a token
refresh request, so no unobserved refresh contract is assumed.

Home Assistant persists the access/refresh token envelope and the app's stable
device UUID in the config entry. A restart restores that session without a new
login. Fresh token values are saved after any later reauthentication and all
token/device fields are removed from diagnostics.

The ON adapter also reuses the current app bearer for read-only Hub health
enrichment. It does not create or persist a separate Hub browser session.

The captured private API returned `x-ratelimit-limit: 250` on normal routes and
`x-ratelimit-limit: 3` on login, without an interval header. The coordinator's
30-second cadence stays far below that request budget, skips team discovery
after IDs are known, and backs off exponentially on HTTP 429. An explicit
`Retry-After` is always honored, even when longer than the fallback cap.
This follows Monta's documented [rate-limit guidance](https://developer.monta.com/docs/integration-notes)
and [fair-use policy](https://developer.monta.com/docs/fair-use-policy) for its
supported APIs.

## Example: signed-in ON app state

```python
client = MontaAppClient(email, password, session=session)

teams = await client.list_teams(team_type="any")
charge_point_ids = await client.list_team_charge_point_ids(teams.items[0]["id"])
snapshot = await client.get_charger_snapshot(charge_point_ids[0])
active_charge = await client.get_active_charge(charge_point_ids[0])
```

The team-card route, rather than `/charge_points`, discovers the three assigned
apartment EVSEs. During an active charge, `active_charge.power_kw` is populated
from the app's latest charge-point measurement.

## Example: supported Public API

```python
client = MontaPublicClient(client_id, client_secret, session=session)

await client.authenticate()
charges = await client.list_charge_sessions(
    charge_point_id=6440650,
    page=0,
    per_page=20,
)
wallet = await client.get_personal_wallet()
```

The current ON application credential can read historical charges and wallet
data but receives no authorized charge points. A manual ID does not bypass that
resource authorization.

## Example: read-only permanent-link state

```python
client = MontaDeeplinkClient(session=session)

summary = await client.get_summary("cp6440650")
snapshot = await client.get_charger_snapshot(6440650)
```

`get_summary()` is public. `get_charger_snapshot()` creates an anonymous guest
identity because the richer endpoint requires a guest bearer token. The guest
is unrelated to the signed-in ON account and monthly invoice arrangement.

## Control safety

No command runs automatically. Each control method requires an explicit call.

The APIs use different payer and resource semantics:

* Public start accepts a charge-point ID and uses the application user's
  authorized payment context.
* App start requires an eligible `paying_team_id`; the ON monthly/account-credit
  option is returned by `list_paying_teams()`.
* Partner start requires `paying_team_id` and supports optional limits.
* Hub start requires `user_id` and accepts an explicit paying team/price group.
* Guest start requires a completed Stripe or Adyen payment reference and must
  not be used as a substitute for ON monthly billing.
* Public, app and guest stop use `POST`; the current Partner contract uses
  `GET`.
* App cable release uses a mutating `GET` route and must remain an explicit
  command despite the misleading HTTP verb.

Administrative Partner/Hub commands such as reboot, maintenance, firmware and
charging-profile changes are intentionally not wrapped.

## Home Assistant integration

The version-3 config flow authenticates with the ON account, discovers charger
cards across its teams and stores the selected charge-point and team IDs. The
coordinator polls charger detail every 30 seconds and session history every ten
polls. Active session IDs are resolved from the charge list because Monta IDs
can exceed JavaScript's exact integer range.

`MontaOnIsClient` translates normalized records into the established entity
contract. Existing version-2 entries retain their old connector ID solely for
Home Assistant device/entity identity; all Monta calls use the selected
charge-point ID. Account-credit start chooses an eligible paying team exactly
as the ON app does. Stop and cable release require an explicit entity action.

Hub charger health is refreshed at most every five minutes and cannot make the
normal app-backed coordinator update fail. Firmware, connection health,
protocol and connector errors, meter certification, lifetime counters,
stability score and signal strengths are mapped when present. A forbidden
station-log route is marked unavailable after one attempt per process instead
of being retried on every refresh.

Only IDs, required account credentials and the reusable app session envelope
are persisted. Raw API responses, recovery links and capture contents are never
written to the config entry or diagnostics.
