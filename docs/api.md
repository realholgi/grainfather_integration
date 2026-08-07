# Grainfather Cloud API

This document describes the Grainfather cloud API as consumed by this integration.
It is derived from the client implementation in
[`custom_components/grainfather/api.py`](../custom_components/grainfather/api.py)
and is intended as a reference for maintainers and contributors.

> **Note**
> This is an unofficial description of a private, undocumented API. Endpoints,
> payloads, and behaviour can change without notice. Nothing here is endorsed by
> Grainfather.

## Base URL

```
https://community.grainfather.com/api
```

All paths below are relative to this base URL.

## Authentication

The API uses email/password login to obtain a bearer token, which is then sent
with every subsequent request.

### `POST /auth/login`

Authenticate with Grainfather credentials.

**Request body (JSON):**

| Field      | Type   | Description             |
|------------|--------|-------------------------|
| `email`    | string | Grainfather account email |
| `password` | string | Grainfather account password |

**Response (JSON):**

The token is read from the first present of these fields:
`api_token`, `accessToken`, or `token`.

Account information is parsed from the same response using the first present of:

| Field        | Source keys                 |
|--------------|-----------------------------|
| `user_id`    | `id`, `userId`              |
| `email`      | `email`                     |
| `first_name` | `firstName`, `first_name`   |
| `last_name`  | `lastName`, `last_name`     |

**Errors:**

- `401` / `403` → invalid credentials.
- A missing token field is treated as an authentication failure.

### Authenticated requests

Every non-login request includes:

| Header          | Value                                   |
|-----------------|-----------------------------------------|
| `Authorization` | `Bearer <token>`                        |
| `Cache-Control` | `no-cache, no-store, max-age=0`         |
| `Pragma`        | `no-cache`                              |

For `GET` requests a cache-busting query parameter `_ts` (current Unix timestamp)
is appended to reduce stale responses from proxies/CDNs.

**Token expiry / retry:** If a request returns `401`/`403`, the client discards the
token, re-authenticates once, and retries the request a single time. A repeated
`401`/`403` is surfaced as an authentication error.

## Brew sessions

### `GET /2/brew-sessions`

List brew sessions, paginated.

**Query parameters:**

| Parameter | Example | Description                          |
|-----------|---------|--------------------------------------|
| `deleted` | `0`     | Exclude deleted sessions             |
| `page`    | `1`     | 1-based page number                  |

**Response (JSON):**

- `data` — array of brew session objects.
- Pagination is followed using the first present of `next_page` / `nextPage`, or
  by parsing the `page` query parameter out of `next_page_url` / `nextPageUrl`.
  Pagination stops when there is no next page (or a page repeats).

### `GET /recipes/{recipe_id}/brew-sessions/{brew_session_id}`

Fetch full detail for a single brew session (including `fermentation_steps`).

The integration fetches this detail for sessions in the `fermenting` state (status
code `20`) to enrich the summary with fermentation steps.

### `PUT /recipes/{recipe_id}/brew-sessions/{brew_session_id}`

Update a brew session. The client sends the full session payload (fetched via the
detail endpoint) with selected fields modified. Used to:

- change the session `status`;
- replace the `fermentation_steps` list.

Before sending, the nested `user.api_token` field (if present) is stripped from the
payload. When replacing fermentation steps, each step is normalized with defaults:
`order` (its index), `time_unit_id` (`30`), `is_ramp_step` (`false`), and
`brew_session_id`.

> **Constraint** Fermentation steps may only be edited while the brew session status
> is below `conditioning` (status code `< 30`).

### Brew session fields

Fields parsed from a brew session payload (summary or detail). Many keys are read
using both snake_case and camelCase variants.

| Field                     | Source keys                                                        |
|---------------------------|--------------------------------------------------------------------|
| `batch_id`                | `id`, `batchId`                                                    |
| `recipe_id`               | `recipe_id`, or `recipe.id`                                        |
| `session_name`            | `session_name`, `sessionName`                                     |
| `recipe_name`             | `recipe.name`, or `name`                                          |
| `condition_date`          | `condition_date`, `conditionDate`                                |
| `fermentation_start_date` | `fermentation_start_date`, `fermentationStartDate`               |
| `created_at`              | `created_at`, `createdAt`                                         |
| `recipe_image_url`        | `recipe.image.url`, `recipe.image_url`/`imageUrl`, `image_url`   |
| `notes`                   | `notes`, `note`, `brew_notes`, `brewNotes`                       |
| `style_name`              | derived from `recipe.recipe_style` / `recipe.style` variants      |
| `batch_variant_name`      | `batch_variant_name`/`batchVariantName`, or `batch_variant.name` |
| `status`                  | `status`, `state`                                                |
| `batch_number`            | `batch_number`, `batchNumber`                                    |
| `original_gravity`        | `original_gravity`, `originalGravity`                            |
| `final_gravity`           | `final_gravity`, `finalGravity`                                  |
| `fermentation_device_ids` | `fermentation_devices` (list of IDs)                             |
| `equipment_name`          | `equipment_profile.name`                                         |
| `fermentation_steps`      | `fermentation_steps`                                             |
| `equipment_profile`       | `equipment_profile`                                             |

### Brew session status codes

| Code | Name          |
|------|---------------|
| `5`  | `planning`    |
| `10` | `brewing`     |
| `20` | `fermenting`  |
| `30` | `conditioning`|
| `35` | `serving`     |
| `40` | `completed`   |

### Fermentation step fields

| Field                | Source key           |
|----------------------|----------------------|
| `step_id`            | `id`                 |
| `name`               | `name`               |
| `temperature`        | `temperature`        |
| `duration`           | `time` (minutes)     |
| `order`              | `order`              |
| `time_unit_id`       | `time_unit_id`       |
| `is_ramp_step`       | `is_ramp_step`       |
| `finish_temperature` | `finish_temperature` |

### Equipment profile fields

| Field          | Source keys                        |
|----------------|------------------------------------|
| `profile_id`   | `id`                               |
| `name`         | `name`                             |
| `brand`        | `brand`, or `profile_brand.name`   |
| `batch_size`   | `batch_size`                       |
| `mash_volume`  | `mash_volume`                      |
| `boil_volume`  | `boil_volume`                      |
| `unit_type_id` | `unit_type_id`                     |

## Fermentation devices

### `GET /equipment/fermentation-devices`

List fermentation devices for the account. Returns a JSON array of device objects.

### Fermentation device fields

| Field                          | Source keys                     |
|--------------------------------|---------------------------------|
| `device_id`                    | `id`                            |
| `name`                         | `name`                          |
| `fermentation_device_type_id`  | `fermentation_device_type_id`   |
| `linked_brew_session_id`       | `brew_session_id`               |
| `linked_brew_session_name`     | `brew_session.session_name`     |
| `last_heard`                   | `last_heard`                    |
| `last_specific_gravity`        | `last_sg`                       |
| `last_temperature`             | `last_temperature`              |
| `is_controller_linked`         | `is_controller_linked`          |

### `GET /equipment/fermentation-devices/{device_id}/history`

Fetch historical readings for a device.

**Query parameters:**

| Parameter | Example      | Description                                        |
|-----------|--------------|----------------------------------------------------|
| `from`    | `2001-01-07` | Start date (`YYYY-MM-DD`). Defaults vary by caller |
| `format`  | `raw`        | Data format                                        |
| `metric`  | `true`       | Metric units (lower-cased boolean string)          |

The integration requests the last 90 days of `raw`, metric data.

**Response (JSON):** either a JSON array of reading objects, or an object with a
`data` array of reading objects.

### History point fields

Each reading is parsed into a history point. Readings with neither a temperature nor
a specific gravity are skipped.

| Field              | Source keys                                                                                   |
|--------------------|-----------------------------------------------------------------------------------------------|
| `device_id`        | (the requested device)                                                                        |
| `brew_session_id`  | `brew_session_id`, `brewSessionId`, `batch_id`, `batchId`                                      |
| `timestamp`        | `timestamp`, `recorded_at`/`recordedAt`, `created_at`/`createdAt`, `date`, `datetime`, `time`, `last_heard` |
| `temperature`      | `temperature`, `temp`, `last_temperature`                                                     |
| `specific_gravity` | `specific_gravity`/`specificGravity`, `gravity`, `sg`, `last_sg`, `last_specific_gravity`     |

## Snapshot polling

`GrainfatherApiClient.async_get_snapshot()` combines the endpoints above into a
single snapshot the integration polls on a schedule:

1. List all brew sessions (paginated).
2. For each `fermenting` session (status `20`), fetch full detail to include
   fermentation steps.
3. List fermentation devices.
4. For each device, fetch the last 90 days of history and index the points both by
   device ID and by linked brew session (batch) ID.

## Service actions

The integration exposes these Home Assistant services (see
[`custom_components/grainfather/services.yaml`](../custom_components/grainfather/services.yaml)),
which map onto the write endpoints above:

| Service                                       | API operation                                                   |
|-----------------------------------------------|-----------------------------------------------------------------|
| `set_brew_session_status`                     | `PUT` brew session with new `status`                            |
| `set_fermentation_steps`                      | `PUT` brew session with a replacement `fermentation_steps` list |
| `set_fermentation_step_duration`              | `PUT` brew session, updating one step's fields                  |
| `clear_fermentation_step_finish_temperature`  | `PUT` brew session, clearing one step's finish temperature      |
| `adjust_current_step_temperature`             | `PUT` brew session, setting the active step temperature         |
| `adjust_current_step_duration`                | `PUT` brew session, setting the active step duration            |
| `advance_to_next_fermentation_step`           | `PUT` brew session, shortening the active step to elapsed time  |

The `status` field of `set_brew_session_status` accepts either a numeric status code
or one of the names: `planning`, `brewing`, `fermenting`, `conditioning`, `serving`,
`completed`.

## Errors

| Exception                        | Meaning                                             |
|----------------------------------|-----------------------------------------------------|
| `GrainfatherAuthenticationError` | Invalid credentials or an expired/rejected session. |
| `GrainfatherApiError`            | Any other failed request or API-level error.        |
