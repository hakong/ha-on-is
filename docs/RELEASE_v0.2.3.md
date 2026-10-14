# v0.2.3

- Preserve Monta's meaning in readable charger states, including Busy (not
  released), instead of masking explicit states with Preparing.
- Retain Preparing for available chargers with a cable attached and Busy (paused)
  when the API explicitly reports a paused session. Generic pauses no longer
  incorrectly blame the vehicle.
- Start readiness describes start eligibility, not whole-charger availability.
- Parse the ON app's exact failed_reason field and expose failure_code separately
  from readable error text.
- Retrieve detail for the latest terminal session during the existing history
  refresh, preserving diagnostics through sparse summaries and HA restarts.
- Rename Last Session State to Previous Session State, keeping entity IDs stable,
  and expose session/charging start, session end, and failure timestamps.
- Include an optional, bounded retry automation with notifications. It retries
  only confirmed StartTransactionTimeout failures, not payment rejections,
  existing sessions, or uncertain outcomes. Customize entity and notify IDs.

HACS updates integration code only. The example automation must be installed
separately; no start commands or automations are installed by this release.
