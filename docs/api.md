# Grainfather Cloud API

This document describes the Grainfather cloud API as consumed by this integration.
It is derived from the client implementation in
[`custom_components/grainfather/api.py`](../custom_components/grainfather/api.py)
and from responses observed while exercising the live API. It is intended as a
reference for maintainers and contributors.

> **Note**
> This is an unofficial description of a private, undocumented API. Endpoints,
> payloads, and behaviour can change without notice. Nothing here is endorsed by
> Grainfather.

> **Verified**
> The endpoints, fields, and enum values below were verified against the live API
> (`https://community.grainfather.com/api`) on 2026-08-07 with a real account.
> Fields marked _(not consumed)_ are returned by the API but not currently mapped
> by the integration. Sections tagged _(undocumented, verified live)_ were
> discovered by probing and are not used by the integration yet.

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
`api_token`, `accessToken`, or `token`. In practice the live API returns
`api_token`.

Account information is parsed from the same response using the first present of:

| Field        | Source keys                 |
|--------------|-----------------------------|
| `user_id`    | `id`, `userId`              |
| `email`      | `email`                     |
| `first_name` | `firstName`, `first_name`   |
| `last_name`  | `lastName`, `last_name`     |

**Observed response fields (live):** `id` (int), `first_name`, `last_name`,
`name` (full name), `email`, and `api_token`. The camelCase variants the client
also accepts were not observed; the live API uses snake_case.

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

The response is a standard Laravel-style paginator object:

- `data` — array of brew session objects.
- `current_page`, `per_page`, `from`, `to` — page metadata (`per_page` observed
  as `10`).
- `current_page_url`, `first_page_url`, `next_page_url`, `prev_page_url`, `path` —
  pagination URLs. `next_page_url` / `prev_page_url` are `null` at the ends.

The client follows pagination using the first present of `next_page` / `nextPage`,
or by parsing the `page` query parameter out of `next_page_url` / `nextPageUrl`.
Pagination stops when there is no next page (or a page repeats).

> **Note** The live API returns `next_page_url` (a full URL with `?page=N`), not a
> bare `next_page` field; the client's URL-parsing branch is the one exercised.

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

### Raw brew session payload _(verified live)_

Beyond the fields the integration maps above, a brew session object returned by
`/2/brew-sessions` and the detail endpoint contains many more fields _(not
consumed)_. Observed top-level keys:

`id`, `unit_type_id`, `notes`, `grain_weight`, `grain_temp`, `boil_time`,
`boil_volume_est`, `ferment_volume_est`, `target_mash_temp`, `mash_thickness`,
`runoff_volume`, `total_water_needed`, `strike_water_temp`, `strike_water_volume`,
`first_runnings_volume`, `sparge_water_volume`, `brew_kettle_loss`,
`wort_shrinkage`, `mash_tun_loss`, `boil_loss`, `mash_grain_absorption`,
`sparge_grain_absorption`, `mash_ph`, `mash_start_temp`, `mash_end_temp`,
`mash_time`, `boil_volume_actual`, `pre_boil_gravity`, `boil_time_actual`,
`post_boil_volume`, `ferment_volume_actual`, `original_gravity`, `final_gravity`,
`condition_date`, `condition_id`, `priming_sugar_type`, `priming_sugar_amount`,
`keg_psi`, `is_active`, `is_public`, `recipe_id`, `user_id`, `created_at`,
`updated_at`, `equipment_profiles_id`, `status`, `fermentation_start_date`,
`no_sparge`, `is_managed`, `delayed_heating_starts_at`, `source_water_profile_id`,
`target_water_profile_id`, `water_calculator`, `deleted_at`, `source`,
`conditioning_temperature`, `conditioning_duration`, `volumes_of_co2`,
`conditioning_volume`, `keg_volume`, `forced_carbonation_psi`,
`volume_per_bottle`, `priming_sugar_rate`, `number_of_bottles`,
`priming_sugar_ppg`, `is_priming_sugar_custom`, `is_calc_volsco2`, `name`,
`batch_number`, `batch_variant_name`, `parent_batch_id`,
`fg_source_fermentation_device_id`, `is_fg_autofilled`, `last_fg_autofilled_date`,
`fermentation_devices` (array of device IDs), `fermentation_steps`,
`fermentation_notifications`, `session_name`, `source_water_profile`,
`target_water_profile`, `recipe` (nested), `equipment_profile` (nested `{id, name}`
in list view).

The single-session **detail** endpoint additionally embeds a full `user` object
(including `api_token`, which the client strips before any `PUT`). The
`recipe.recipe_style` object supplies the style name via `sub_category_name`.

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

**Raw device payload _(verified live)_** — additional fields returned but _(not
consumed)_: `device_token`, `user_id`, `created_at`, `updated_at`,
`particle_device_id`, `unique_device_token`, `serial_no`, `data_updated_at`,
`firmware_ver`, `firmware_updated_at`, `source_fermentation_device_id`,
`esp_chip_id`, and a fully embedded `brew_session` object (same shape as a brew
session, minus the `user`).

### `fermentation_device_type_id` values _(verified live)_

| Value | Device                | Readings                                    |
|-------|-----------------------|---------------------------------------------|
| `10`  | Hydrometer / pill     | `temperature` **and** `specific_gravity`; populates `last_sg` / `last_temperature` |
| `30`  | Fermentation controller | `temperature` and `target_temperature` (no gravity); `is_controller_linked = true` |

### `GET /equipment/fermentation-devices/{device_id}/history`

Fetch historical readings for a device.

**Query parameters:**

| Parameter | Example      | Description                                        |
|-----------|--------------|----------------------------------------------------|
| `from`    | `2001-01-07` | Start date (`YYYY-MM-DD`). Defaults vary by caller |
| `format`  | `raw`        | Data format                                        |
| `metric`  | `true`       | Metric units (lower-cased boolean string)          |

The integration requests the last 90 days of `raw`, metric data.

**Parameter behaviour _(verified live)_:**

- `metric=true` returns Celsius; `metric=false` returns Fahrenheit (e.g. the same
  reading was `~28.8` vs `83.8`). Gravity values are unaffected.
- `format` was accepted for the values `raw`, `hourly`, `daily`, and `average`, but
  all returned the same number of points in testing — no visible aggregation for
  the ranges tried. `raw` is the safe default.

**Response (JSON):** either a JSON array of reading objects, or an object with a
`data` array of reading objects. In practice a bare JSON array is returned.

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

**Observed reading fields _(verified live)_:** `id`, `token`, `timestamp`, `local`
(local-time string), `recipe_name`, `brew_session_id`, `temperature`, `updated_at`,
`deleted_at`, plus **either** `specific_gravity` (pill / type `10`) **or**
`target_temperature` (controller / type `30`).

## Additional endpoints (undocumented, verified live)

These endpoints were discovered by probing the live API. All require the
`Authorization: Bearer <token>` header. Except where noted, they are not used by
the integration yet but are documented here for future work.

### `GET /users/me`

Returns the authenticated user as a single object. Observed fields: `id`,
`first_name`, `last_name`, `name`, `email`, `role`, `type`, `region`,
`country_subdivision`, `city`, `geo_location`, `nickname`, `bio`, `brewery_name`,
`status`, `notifications`, `notify_whats_new`, `last_read_notifications`,
`brewing_101_chapter`, `brewing_skill_level_id`, `has_completed_onboarding`,
`email_verified_at`, `is_recipe_provider`, `beta`, `has_viewed_tour`,
`is_gcast_beta`, `grainkit_shop`, `image` (nested), `notification_messages`,
`last_seen_at`, `created_at`, `updated_at`, `deleted_at`, plus the secret
`api_token`, `email_uid`, `salt` fields.

### `GET /recipes`

Returns a lightweight JSON **array** of the account's recipes. Each item only
contains: `id`, `name`, `description`, `status` (e.g. `current`). Useful for
building a recipe picker without the full payload.

### `GET /2/recipes`

Paginated full recipes, using the same Laravel paginator shape as
`/2/brew-sessions` (`current_page`, `per_page` ~ `10`, `next_page_url`, `data`,
etc.). Accepts a `page` query parameter. Each `data` item is a full recipe object
(see `GET /recipes/{recipe_id}`).

### `GET /recipes/{recipe_id}`

Full detail for a single recipe. The integration calls this endpoint when a
brew-session's embedded recipe lacks required metrics or ingredients; requests
are cached per recipe ID for the duration of a snapshot refresh. Notable fields
_(verified live)_:

- Core: `id`, `name`, `description`, `notes`, `image_url`, `batch_size`,
  `boil_size`, `boil_time`, `efficiency`, `og`, `fg`, `srm`, `ibu`, `bggu`,
  `abv`, `calories`, `losses`, `unit_type_id`, `recipe_type_id`, `style_id`,
  `bjcp_style_id`, `equipment_profile_id`, `source_water_profile_id`,
  `target_water_profile_id`, `hash`, `source`, `view_count`, `copy_count`,
  `brew_session_count`, `ranking_score`, `is_active`, `is_public`, `is_archived`,
  `is_searchable`, `is_bookmarked_by_user`, `is_liked_by_user`, `recipe_likes`,
  `recipe_dislikes`, `created_at`, `updated_at`, `deleted_at`.
- Nested ingredient lists: `fermentables[]` (`name`, `amount`, `ppg`, `lovibond`,
  `fermentable_usage_type_id`, `supplier`, `usage_type{id,name}`), `hops[]`
  (`name`, `amount`, `aa`, `time`, `ibu`, `order`, `hop_type_id`,
  `hop_usage_type_id`, `type{}`, `usage_type{}`), `yeasts[]` (`name`,
  `attenuation`, `amount`, `unit`, `product_code`), `adjuncts[]`, `mash_steps[]`
  (`name`, `temperature`, `time`, `order`), `fermentation_steps[]`.
- Nested objects: `recipe_style` (full BJCP style, see below), `equipment_profile`
  (full profile, including controller/hardware fields such as
  `equipment_profile_type_id`, `controller_type_id`, `cooling_method_id`, etc.),
  `type{id,name}`, `unit_type{id,name}`, `parent_recipe`, `media[]`.

### `GET /recipes/{recipe_id}/brew-sessions`

Returns a JSON **array** of brew-session stubs for a recipe. Observed fields per
item: `id`, `created_at`, `updated_at`, `deleted_at`. Combine the `id` with the
`recipe_id` to call the brew-session detail endpoint.

### `GET /recipe-styles`

Returns a large JSON **array** of style definitions (316 entries observed - the
full BJCP catalogue). Each style includes: `id` (e.g. `23D`), `class` (e.g.
`beer`), `category_id`, `category_name`, `sub_category_id`, `sub_category_name`,
`aroma`, `appearance`, `flavor`, `mouthfeel`, `impression`, `comments`,
`ingredients`, `examples`, the `*_low` / `*_high` ranges for `og`, `fg`, `ibu`,
`srm`, `abv`, `display_sub_category_id`, `extended_data`, `style_type` (e.g.
`bjcp_beer`), `created_at`, `updated_at`.

### `GET /unit-types`

Returns the unit systems as a JSON array _(verified live)_:

| `id` | `name`        |
|------|---------------|
| `10` | `Metric`      |
| `20` | `US Standard` |

### Endpoints that returned `404`

While probing, the following guessed paths returned `404` and do **not** exist (at
least not under these names): `/user`, `/me`, `/account`, `/profile`,
`/brew-sessions`, `/2/brew-sessions/{id}`, `/equipment-profiles`,
`/equipment/equipment-profiles`, `/water-profiles`, `/inventory`, `/styles`,
`/notifications`, `/fermentation-devices` (without the `/equipment` prefix),
`/fermentation-device-types`, `/hops`, `/fermentables`, `/yeasts`, `/adjuncts`,
`/miscs`, `/units`, `/time-units`, `/conditions`, `/priming-sugars`,
`/dashboard`, `/countries`, `/regions`, `/brewing-skill-levels`. Reference data
for equipment profiles, water profiles, and ingredients appears to be embedded in
the recipe/brew-session payloads rather than exposed as standalone collections.

## Snapshot polling

`GrainfatherApiClient.async_get_snapshot()` combines the endpoints above into a
single snapshot the integration polls on a schedule:

1. List all brew sessions (paginated).
2. For each `fermenting` session (status `20`), fetch full detail to include
   fermentation steps.
3. For each brew session whose embedded recipe lacks required metrics or
   ingredients, fetch full recipe detail once per recipe ID and merge it into the
   session.
4. List fermentation devices.
5. For each device, fetch the last 90 days of history and index the points both by
   device ID and by linked brew session (batch) ID.

### Adaptive interval

The Grainfather cloud API is REST-only (no websocket, MQTT, or webhook is exposed to
third parties), so the integration cannot receive true server-side push. Instead of a
single fixed cadence, `GrainfatherDataUpdateCoordinator` chooses its next poll interval
after every refresh based on the current snapshot:

- **Active interval** (`active_scan_interval`, default 60 s) — used when the snapshot is
  "active": any brew session has status `10` (brewing) or `20` (fermenting), or a
  fermentation controller is `is_controller_linked` and its `last_heard` timestamp is
  recent (within one hour).
- **Idle interval** (`scan_interval`, default 300 s) — used otherwise, to keep load on
  the Grainfather cloud and Home Assistant low.
- **Post-action boost** — after any write (a service call or a number/select entity
  write) the coordinator triggers an immediate refresh and stays on the active interval
  for a short window (120 s) so the change and any device-side follow-up surface quickly.

Both intervals are clamped to `MIN_SCAN_INTERVAL` (60 s) / `MAX_SCAN_INTERVAL` (3600 s).
The activity decision (`snapshot_is_active`) and interval choice (`compute_update_interval`)
live in `custom_components/grainfather/polling.py` as pure, unit-tested functions. The
integration remains classified `iot_class: cloud_polling` — adaptive polling is still
polling.

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
