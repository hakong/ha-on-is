# ON app feature matrix

Research source: the 2026-09-20 Android capture containing 447 requests and 65
distinct method/path combinations. This covers features observed during that
session; it is not a claim that every feature in every ON/Monta account was
captured.

Status legend:

* **Yes**: implemented and exposed through Home Assistant.
* **Partial**: some data is exposed, or only the most useful subset exists.
* **Client**: reusable API method exists, but no Home Assistant entity/action.
* **No**: neither the signed-in client nor Home Assistant exposes it.
* **Failed**: the captured request did not establish a working contract.

## User actions recorded in the app

| App action | Captured API operation | Result | API client | Home Assistant |
| --- | --- | --- | --- | --- |
| Sign in | `POST /api/v1/auth/login` | 1 successful login | Yes | Yes; session token and device UUID are reused |
| Start charging with ON account credit | `POST /api/v1/charges/start` | 2 successful starts | Yes | Yes; charging switch |
| Observe asynchronous start failure | `GET /api/v1/charges/{id}` | Failed charge can be `state=completed` with `failed_at` and `error` | Yes | Yes; status and latest-session state/error |
| Save charging defaults after start | `PUT /api/v1/users/charge_point_settings` | 2 successful writes | Client | No |
| Stop charging | `POST /api/v1/charges/{id}/stop` | 1 successful asynchronous stop | Yes | Yes; charging switch |
| Release cable | `GET /api/v1/charge_points/{id}/integrations/{id}/unlock` | 1 successful unlock | Yes | Yes; button stops an accessible active charge, waits for completion, then requests unlock |
| View charging sessions | `GET /api/v1/charges` and `/charges/{id}` | History and detail loaded repeatedly | Yes | Partial; active and latest completed session |
| View receipt | `GET /api/v1/wallet/receipts/charges/{id}` | Receipt metadata returned | Client | Partial; availability and charge ID only |
| Download receipt PDF | `GET /wallet/receipts/{uuid}/download` | Redirected to download | No | No |
| Add a favorite charger/site | `POST /api/v1/favorites` | 1 favorite created | No | No |
| Rate a completed charge | `POST /api/v1/ratings` | 1 rating created | No | No |
| Mark app-rating prompt complete | `POST /api/v1/users/me/rated_app` | Successful | No | No |
| Edit team/profile billing details | `PATCH /api/v1/teams/{id}` | 2 attempts returned HTTP 422 | Failed | No |
| Request personal data export | `POST /api/v1/users/me/data_request` | Returned HTTP 400 | Failed | No |

## Charger and charging features

| Feature | Captured API | API client | Home Assistant |
| --- | --- | --- | --- |
| Discover assigned apartment chargers | Teams plus team charger cards | Yes | Yes; setup selection and migration matching |
| Charger identity and address | Charge-point detail | Yes | Partial; identity/model data, address omitted for privacy |
| Connector type and maximum power | Charge-point detail | Yes | Yes |
| Firmware, manufacturer, model and serial | Charge-point detail | Yes | Yes; device metadata where supplied |
| Protocol/connector/vendor errors | Hub charge-point detail | Yes | Yes; health diagnostic attributes |
| Firmware status and update availability | Hub charge-point detail | Yes | Yes; firmware diagnostic sensor |
| Stability score | App model and Hub charger detail | Yes | Yes; diagnostic sensor with score scope |
| Lifetime charge count | Hub charge-point detail | Yes | Yes; diagnostic sensor |
| OCPP, MID and meter accuracy | App/Hub integration detail | Yes | Yes; health diagnostic attributes |
| Wi-Fi and cellular strength | App/Hub integration detail | Yes | Yes when supplied; currently null on Zaptec Cloud |
| Charging-station logs | Hub Control logs | Access denied for this account | No; availability/error shown diagnostically |
| Charger cloud connection | Integration state | Yes | Yes; connectivity binary sensor |
| Cable plugged/unplugged | Top-level `cable_plugged_in` | Yes | Yes; plug binary sensor |
| Available/preparing/starting/paused/charging/stopping/completed/failed state | Charger and charge detail | Yes | Yes; status sensor |
| Start eligibility and rejection reason | `details.can_start` and reason | Yes | Yes; status attributes |
| Account-credit payer selection | `/teams/pay-charge` | Yes | Yes; automatic eligible-team selection |
| Price per kWh and currency | Charger pricing | Yes | Yes; rounded price sensor |
| Active session ID and timestamps | Active charge/detail | Yes | Yes |
| Live power | `last_measurement.kw_charge_point` | Yes | Yes |
| Session energy, cost and duration | Charge detail | Yes | Yes |
| Phase current and voltage | Last measurement | Yes | Yes; disabled by default, observed values were null |
| Vehicle state of charge | Charge detail | Yes | Yes; disabled by default, observed value was null |
| Lifetime charger meter | Charge-point details | Yes | Yes; disabled by default |
| Estimated kWh, price and completion time | Charge-point details | Yes | Yes; status attributes |
| Smart-charge and auto-charge capability flags | Charge-point details | Yes | Yes; status attributes |
| Full paginated charging history | Charges collection | Yes | Partial; latest completed session only |
| Receipt totals, line items and URLs | Receipt endpoint | Yes | Partial; safe metadata only, URLs are not recorded |
| Fixed-kWh charging target | Saved charge-point settings | Client | No; non-default write not yet validated |
| Percentage/SoC charging target | Saved charge-point settings | Client | No; charger returned no SoC |
| Scheduled start and pickup time | Saved charge-point settings | Client | No; non-default write not yet validated |
| Vehicle association for a charge | Settings plus vehicles | Client | No |
| Smart charging mode | Charge-point settings/capabilities | Partial client | No; unavailable for this charger/account |

## Account, billing and vehicle features

| Feature | Captured API | API client | Home Assistant |
| --- | --- | --- | --- |
| Current user/profile | `/users/me` | Client | No |
| Connected applications | `/users/me/applications` | No | No |
| Personal wallet team | `/teams/personal` | Client | No |
| Team detail and payment arrangement | `/teams/{id}` | Client | Partial; payer method appears on status/session attributes |
| Team membership and permissions | Teams and membership routes | Partial client | No |
| Pending members and invitations | Team member/invite routes | No | No |
| Team price groups | `/teams/{id}/price_groups` | No | No |
| Plans/subscriptions | `/api/app/bff/me/subscriptions` | Client | No |
| Subscription detail | `/subscriptions/details` | No | No |
| Subscription payments | `/subscriptions/details/payments` | No | No |
| Team transactions | `/transactions/teams/{id}` | Client | No |
| Saved vehicles and integrations | `/vehicles` | Client | No |
| Team charge keys/auth tokens | Wallet charge-point-auth-token routes | No | No |
| Bank accounts | Wallet bank-account route | No | No |
| Saved card/Stripe sources | Wallet Stripe routes | No | No |
| Promotion codes | `/promotion_codes/` | No | No |

## Discovery, support and app-only features

| Feature | Captured API | API client | Home Assistant |
| --- | --- | --- | --- |
| Charger map, filters and markers | Map BFF and preconfigured filters | No | No |
| Site and charger-group map detail | Map site routes | No | No |
| Text/unified charger search | `/unified-search` | No | No |
| Reverse geocoding and place detail | Geocoder/country routes | No | No |
| Favorite charger cards | Favorite cards plus favorites write | No | No |
| Smart queues | `/utilization/smart-queues` | No | No |
| Public usage/forecast insights | `/insights/public` | No | No |
| In-app notifications, unread count and events | Notification routes | No | No |
| OS push notifications | Firebase/APNs transport was not reconstructed | No | No; charge failures are polled from charge detail instead |
| Service incidents affecting a charger | `/status/incidents` | No | No |
| Support entry points | `/support/` | No | No |
| Support chats and unread count | Chat routes and external support requests | No | No |
| Charge ratings | Ratings write | No | No |
| App onboarding | App onboarding BFF | No | No |
| Server-controlled feature flags | Features, user features and user segments | No | No |
| Deeplink resolution | `/deeplinks/payload` | No in app client; separate deeplink client exists | No |
| Countries and subscribable plans | Country and plan routes | No | No |

## Recommended next additions

1. **Receipt retrieval service:** return receipt metadata or a short-lived URL
   only in a service response so secrets are not stored in entity state or the
   recorder.
2. **Account-credit diagnostics:** low-frequency sensors for payer eligibility,
   payment arrangement and subscription status. These help explain why start
   is allowed or rejected without exposing bank/card details.
3. **Richer session history:** expose several recent sessions through a
   calendar/event-style interface or a response-producing service rather than
   creating an unbounded number of sensors.
4. **Charging preferences:** add explicit controls for full/fixed-kWh,
   scheduled start and pickup time only after capturing successful non-default
   writes and their validation/error behavior.
5. **Vehicle selection:** expose saved vehicles and optional charge association
   if vehicle-linked SoC or reporting proves useful.
6. **Incidents and notifications:** add a diagnostic event/sensor for charger
   incidents. General app marketing notifications and chats should stay out of
   a charger integration.

Map browsing, favorites, ratings, promotion codes, bank/card management,
profile editing and support chat offer little Home Assistant value and should
remain app-only unless a concrete automation use case emerges.
