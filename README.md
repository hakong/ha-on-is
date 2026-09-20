# ON (Orka náttúrunnar) for Home Assistant

Unofficial Home Assistant integration for the Icelandic [ON (Orka náttúrunnar)](https://on.is) EV charging network.

Version 0.2 uses the Monta backend that powers the current ON app. The retired
Etrel OCEAN client remains in the source only as a compatibility building block.

<img src="https://github.com/hakong/ha-on-is/blob/main/images/dashboard.png?raw=true" width="600" alt="Home Assistant Dashboard Screenshot">

## Features

* **Charger discovery:** Finds chargers assigned through Monta team cards and
  lets you select the correct charger in shared installations.
* **State:** Available, cable connected/preparing, starting, paused, charging,
  stopping, completed, failed and disconnected states. Asynchronous start
  failures and Monta's safe error description are retained with the latest
  session.
* **Live monitoring:** Power, session energy, session cost, price and duration.
* **Connection detail:** Separate cable-connected and cloud-connected binary
  sensors, plus a cached last-communication timestamp.
* **Diagnostics:** Health summary, protocol and connector errors, firmware
  status, stability score, charge count, last connection, OCPP/MID and meter
  information. Slow-changing Hub details are refreshed every five minutes
  using the existing ON app session.
* **History:** State, cost, energy, duration, payment, failure and receipt
  metadata for the latest session or charging attempt.
* **Control:** Account-credit start/stop and explicit cable release actions.
* **Optional telemetry:** Per-phase current/voltage, vehicle SoC and lifetime
  meter sensors are created disabled by default because the charger may return
  no values for them.

## Installation

### Option 1: HACS (Recommended)
1.  Open **HACS** > **Integrations**.
2.  Click the **3 dots** (top right) > **Custom repositories**.
3.  Add this repository URL.
4.  Category: **Integration**.
5.  Search for **ON** and click **Download**.
6.  Restart Home Assistant.

### Option 2: Manual
1.  Copy the `custom_components/on_is` folder to your Home Assistant `config/custom_components/` directory.
2.  Restart Home Assistant.

## Configuration
1.  Go to **Settings** > **Devices & Services**.
2.  Click **Add Integration**.
3.  Search for **ON (Orka náttúrunnar)**.
4. Enter the email and password used by the ON app.
5. Select the charger to add. Add the integration again to configure another
   charger from the same account.

## ON app migration

Existing version-2 entries migrate automatically from OCEAN to Monta. The
migration matches the old ON charger number to Monta and retains the old
connector-based unique IDs so existing entities, history and dashboards remain
attached.

The production path uses the same signed-in private API as the ON Android app.
It persists the bearer session and stable app-device UUID so a Home Assistant
restart does not create a new Monta login/device. It reauthenticates only when
the session expires and asks Home Assistant for a new password after an
authentication failure. This private contract may change with a future app
release.

The integration polls every 30 seconds. It observed a 250-request private API
quota and a separate three-request login quota in the ON app responses. Charger
discovery is cached after setup, history is refreshed every five minutes, and
HTTP 429 responses trigger exponential backoff from one minute to 15 minutes
unless Monta supplies a longer `Retry-After` value.

See [Monta API clients](docs/MONTA_API_CLIENTS.md) for the implementation map
and [ON app feature matrix](docs/APP_FEATURE_MATRIX.md) for captured operations,
implementation status and known gaps.

## Disclaimer
This is a reverse-engineered integration and is not affiliated with Orka
náttúrunnar, Monta or Etrel. Use at your own risk.
