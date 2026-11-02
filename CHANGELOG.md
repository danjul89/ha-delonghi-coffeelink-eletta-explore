# Changelog

All notable user-visible changes are documented here. The project follows
[Semantic Versioning](https://semver.org/) and uses the principles of
[Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

### Fixed

- Send Coffee Link's `0xe8 0xf0` statistics request instead of the `03 02`
  session refresh when synchronizing statistics. On Eletta Explore the `03 02`
  frame only republished `d302`, so beverage counters stayed frozen until the
  official app was opened or the appliance reconnected to Wi-Fi; a week of drinks
  then arrived as one jump. The new frame makes the appliance upload changed
  counters within about twenty seconds, also from standby.

### Added

- Request a statistics snapshot when a beverage prepared at the machine finishes
  (live monitor returns from preparing to ready), so counters follow within
  seconds instead of waiting for the hourly sync. Diagnostics report this as the
  `beverage_finished` trigger.

## [1.3.1] - 2026-09-30

### Fixed

- Respect the cloud's Retry-After interval when reconnecting an Ayla DSS stream
  after rate limiting, while retaining the polling fallback.
- Include the connection phase and HTTP status in the first DSS fallback warning
  without logging exception messages, credentials, stream keys or account data.

### Validation

- Pass 402 isolated tests with 100% line and branch coverage, three tests against
  actual Home Assistant interfaces, Ruff, strict mypy, HACS and hassfest.
- Install the exact prerelease through HACS on Home Assistant 2026.9.4. The
  integration loaded without a serious log entry, kept the Eletta online and DSS
  streaming, and released its Coffee Link session automatically after the normal
  five-minute window. No appliance command was sent during this acceptance.

## [1.3.0] - 2026-08-31

### Added

- Add a project-neutral support link and an inherited GitHub Sponsor button;
  financial details remain centralized on the privacy-friendly support page.
- Refresh Eletta's device-to-cloud snapshot cooperatively at startup, once per
  hour and after a completed beverage command. The integration sends Coffee
  Link's idempotent `03 02` request, waits up to ten seconds for a relevant DSS
  update and performs an authoritative property reconciliation.
- Add privacy-safe runtime diagnostics for snapshot attempts, successes, trigger,
  ACK status and whether the counter snapshot changed. No new entity or recorder
  history is created.

### Fixed

- Make **Refresh cloud data** request a new snapshot from the appliance instead
  of merely rereading the vendor's possibly stale cloud cache.
- Check the live Coffee Link session holder before every cloud-session claim.
  Automatic refresh is deferred while the coffee maker is offline, preparing a
  drink, processing another Home Assistant command or held by a foreign session.
- Keep automatic snapshot traffic separate from **Last Command Status** so
  maintenance refreshes cannot appear as user-issued appliance commands.
- Transparently renew a server-rejected Ayla access token through the in-memory
  refresh token, with a full-login fallback, and replay the refused request
  exactly once.
- Start Home Assistant reauthentication only when Gigya explicitly rejects the
  saved account credentials. Expired sessions, rejected token exchanges and
  persistent cloud authorization failures now remain availability errors instead
  of incorrectly asking for the password again.

### Changed

- Rename the disabled recipe diagnostic button to **Log recipe data** in
  English and **Zapsat data receptů** in Czech; keep its entity identity,
  diagnostic category and disabled-by-default behaviour unchanged.
- Rename the manual cloud refresh button to **Refresh cloud data** in English
  and **Načíst data z cloudu** in Czech, classify it as diagnostic and disable
  it by default without changing its entity identity or refresh behaviour.
- Document the difference between the calculated grounds-container percentage
  and the authoritative full/missing alarm, including the manufacturer-required
  awake-machine procedure for resetting the grounds counter.

## [1.3.0-beta.6] - 2026-08-21

### Changed

- Confirm commands from DSS state-change events while the cloud stream is
  healthy; retain one authoritative reconciliation after timeout and the
  bounded polling path when streaming is unavailable.
- Share the slowly changing account device list through a lock-protected cache,
  preventing one identical cloud request per machine during reconciliation.
- Move persistent recipe restoration into the coordinator setup phase, use
  monotonic clocks for runtime deadlines and remove duplicate coordinator
  shutdown work and unused client/device state.
- Use the current aiohttp WebSocket timeout API and enforce Ruff formatting plus
  strict mypy 2.3.0 checking in CI.

### Fixed

- Forward a sanitized, bounded Ayla `Retry-After` value to Home Assistant's
  coordinator so rate-limited updates are rescheduled correctly.
- Prevent a raw device DSN from reaching request-debug details; operation names
  remain available for troubleshooting.
- Always perform the first optional connection-diagnostics read, including on a
  freshly booted host whose monotonic clock is below the hourly refresh interval.

### Tests

- Keep 100% statement and branch coverage across all 19 Python modules with 373
  isolated tests, plus 3 tests against Home Assistant 2026.8.2 interfaces.
- Complete a backed-up deployment, Home Assistant configuration check, clean
  restart, read-only cloud synchronization and a supervised Wake, Cold Brew
  Start/Stop and Standby cycle on the verified Eletta Explore. The machine
  returned to standby and the Home Assistant system log remained error-free.

## [1.3.0-beta.5] - 2026-08-21

### Added

- Add an account-wide Ayla DSS cloud stream for near-real-time datapoint and
  datapoint-ack updates, with immediate automatic fallback to polling.
- Add exact command confirmation by matching the device acknowledgement to the
  datapoint created by Home Assistant; an explicit device rejection is reported
  separately from a timeout.
- Add a disabled-by-default Wi-Fi signal diagnostic sensor when the vendor cloud
  exposes connection information for the machine.
- Add Coffee Link-equivalent aggregate counters for hot and cold milk drinks.
- Add explicit Coffee Link statistics families for Eletta/Striker Cold Brew and
  the legacy PrimaDonna Soul branch; unknown models never inherit an aggregate
  formula merely from their command channel.

### Changed

- Protect cloud-push state from duplicate, out-of-order and older MonitorV2
  events; retain a five-minute reconciliation poll while streaming and restore
  the normal 30-second interval whenever the stream is unavailable.
- Declare the integration as `cloud_push` and keep polling as a transparent
  reliability fallback.
- Match Coffee Link's Eletta statistics formulas for black coffee and Mug to Go,
  while retaining the established Home Assistant entity unique IDs.
- Correct `d553_water_tot_qty` from half-millilitre ticks to litres; preserve
  the vendor value's three-decimal precision instead of the app's whole-litre
  display truncation.
- Create a fresh, short-lived DSS subscription for every WebSocket connection,
  matching Coffee Link 4.9.6 instead of reusing a stale server stream key.
- Record the privacy-safe ACK status on the Last Command Status entity when DSS
  matches the acknowledgement to the exact datapoint issued by Home Assistant.
- Match Coffee Link's legacy statistics formula: `d700` is the black-coffee
  total, while `d701 + d703` is the hot-milk aggregate. Remove the misleading
  water-dispense interpretation of `d703`; total water remains sourced from
  `d553` and converted to litres.
- Keep semantic summary and maintenance statistics enabled for new entity
  registrations, while making per-recipe and recipe-group counters available
  but disabled by default. Existing Home Assistant entity-registry choices are
  not changed.
- Display the backward-compatible Coffee Link session state `ha` as the neutral
  **Active** / **Aktivní**. The machine-derived identifier is
  shared with the official app and therefore cannot prove which client holds it.
- Restrict reconfiguration to validating a replacement password for the
  existing Coffee Link account. Changing accounts still requires a separate
  config entry, matching Home Assistant's reconfiguration contract.
- Use Home Assistant sentence case for English entity names, retain official
  Coffee Link recipe names and use the correct De'Longhi brand spelling in all
  user-facing English text.

### Fixed

- Honor each command property's cloud-declared ACK capability, matching Coffee
  Link: ACK-enabled models wait up to the Ayla SDK's ten-second window, while
  Eletta's non-ACK command channel immediately uses cloud-state confirmation.
- Match the official Ayla SDK's `x-ayla-source: Mobile` datapoint-write header
  and add privacy-safe DSS event-type/ACK-capability diagnostics.
- Use the shared Eletta learned-recipe catalogue in command diagnostics, so
  Last Command Status reports names such as Cold Brew instead of raw IDs.
- Isolate connection-information and DSS startup in the actual Home Assistant
  runtime test so it cannot contact a vendor endpoint.
- Remove the unverified LAN configuration link from the cloud-only device and
  replace the fallback device name containing its DSN with a privacy-safe name.
- Confirm a pending standby maintenance snapshot during setup so water-tank,
  grounds-container, filter and descale entities do not remain unavailable until
  the five-minute DSS reconciliation poll.

### Security

- Never retain or expose the DSS stream key or Wi-Fi network name. Diagnostics
  include only sanitized stream health, connectivity type and optional RSSI.

### Documentation

- Update the technical audit and English/Czech project status after publication
  of 1.2.1, its verified HACS installation and submission to the default HACS
  catalog review queue.
- Distinguish the installed 1.2.1 release from the 1.2.0 supervised physical
  command-acceptance baseline; 1.2.1 does not change those runtime paths.
- Record the current external HACS catalog check state without presenting it as
  an integration or release-validation failure.
- Record beta.4's backed-up target-HA deployment, clean restart, read-only
  statistics synchronization, loaded English/Czech resources and DSS event
  acceptance without claiming a physical command test.
- Add an explicit prerelease path to the maintainer release process and prepare
  beta.5 as the corrected public release candidate.
- Record beta.5's backed-up deployment, clean restart, loaded English/Czech
  resources, read-only maintenance/DSS acceptance and supervised Wake, Cold Brew
  Start/Stop and Standby acceptance.

## [1.2.1] - 2026-08-19

### Changed

- Prepare the repository for public distribution with stable HACS-first and
  manual installation guidance in English and Czech, a one-click My Home
  Assistant link and a documented maintainer release process.
- Trigger validation automatically when the repository changes from private to
  public, while retaining the public-only guard required by the HACS validator.
- Align custom-integration localization with current Home Assistant guidance:
  `translations/en.json` and `translations/cs.json` are the complete runtime
  sources and the unused core-build `strings.json` duplicate is removed.
- Update compatibility, security and technical-audit statements to reflect the
  completed 1.2.0 physical acceptance and cleaned Git history.

### Security

- Add a stable private-vulnerability-reporting path and a safe non-sensitive
  fallback contact procedure.
- Add repository tests that reject pre-publication wording, obsolete releases,
  duplicate translation sources and unpinned workflow actions.
- Keep 100% line and branch coverage with 312 isolated tests, including local
  Markdown-link validation for the public documentation set.

## [1.2.0] - 2026-08-19

### Added

- Add real-runtime integration tests against Home Assistant 2026.8.2 for the
  config flow, setup, platforms, entity/device registries, diagnostics and
  unload lifecycle.
- Add automatic account-device reconciliation: newly added or removed coffee
  makers trigger one controlled config-entry reload, and stale entity/device
  registry records are removed.
- Add translated Home Assistant Repairs guidance for saved learned commands
  that fail integrity or device-signature validation; the issue clears after
  all discarded commands are learned again.
- Add `icons.json` for every translated entity and action, and a tracked Home
  Assistant integration quality-scale checklist.

### Changed

- Prepare version 1.2.0 and align the code with current Home Assistant 2026.8
  interfaces: `ConfigFlowResult`, typed `ConfigEntry.runtime_data`, an explicit
  coordinator config entry, config-entry-owned background tasks and shared
  entity metadata.
- Declare `PARALLEL_UPDATES = 0` on every coordinator-backed platform and keep
  outbound commands serialized per coffee maker.
- Update documentation, installation guidance, compatibility statements,
  troubleshooting and the technical audit for the 1.2.0 release candidate.
- Pin every GitHub Action to a reviewed full commit SHA and pin CI runners to
  Ubuntu 24.04.

### Security and privacy

- Restrict the administrator raw action to CRC-valid beverage and wake/standby
  frames, require the learned signature of the selected Eletta machine and run
  the normal readiness, water-tank and grounds-container checks for raw starts.
- Remove account/device identifiers and upstream response bodies from routine
  cloud logging, and keep retry detail at debug level to avoid log flooding.
- Replace device signatures in current test fixtures with deterministic
  synthetic bytes and keep the raw-action schema free of an executable example.

### Tests

- Keep 100% line and branch coverage across all 17 Python modules: 311 isolated
  tests covering 2,050 statements and 628 branches.
- Run an additional CI job against the actual Home Assistant 2026.8.2 test
  interfaces on Python 3.14.2.

## [1.1.26] - 2026-08-19

- Reach 100% line and branch coverage for the coordinator and therefore for all
  16 Python modules in the integration.
- Cover polling and metadata refresh, monitor stability, cloud-session ownership
  and confirmation, command acknowledgement, recipe learning and persistence,
  app-traffic attribution, power commands, raw commands, delayed refreshes, and
  all translated error paths with deterministic local doubles.
- Simplify a redundant active-beverage check after a Stop frame has already met
  the same-beverage predicate; runtime behavior is unchanged.
- Raise the CI coverage floor from 83% to 100%; the full suite now contains 305
  tests with 100% overall line and branch coverage.

## 1.1.25 - 2026-08-19

- Reach 100% line and branch coverage for the Gigya/Ayla cloud client without
  contacting a real account or external service.
- Cover authentication locking, token validity and refresh, Gigya login and
  signed JWT exchange, Ayla SSO, credential rejection, transient HTTP errors,
  rate-limit delays, timeouts, malformed responses, and retry exhaustion.
- Cover device and property discovery, property writes, resilient reads, and
  the signed Coffee Link cloud-session payload, including response validation
  and fallback behavior.
- Raise the CI coverage floor from 74% to 83%; the full suite now contains 248
  tests with 83.09% overall branch coverage.

## 1.1.24 - 2026-08-19

- Reach 100% line and branch coverage for the configuration flow and integration
  lifecycle modules.
- Cover initial forms, successful account creation, all authentication and cloud
  validation outcomes, empty accounts, reauthentication, and reconfiguration.
- Cover service registration and execution, target-resolution failures, setup
  authentication and cloud errors, multi-device initialization, partial-failure
  cleanup, platform forwarding, and successful or rejected unloads.
- Raise the CI coverage floor from 70% to 74%; the full suite now contains 223
  tests with 74.83% overall branch coverage.

## 1.1.23 - 2026-08-19

- Reach 100% line and branch coverage for the sensor, binary-sensor, button,
  and binary command-builder modules.
- Cover entity setup and omission rules, counter metadata and parser routing,
  maintenance alarm variants, device-info fallbacks, button migration and
  dynamic learned recipes, action availability, and coordinator calls.
- Add protocol boundary coverage for malformed persistence, short and
  inconsistent frames, power-header validation, Coffee Link session refresh,
  wake validation, and unsigned Eletta frames.
- Raise the CI coverage floor from 60% to 70%; the full suite now contains 215
  tests with 71.48% overall branch coverage.

## 1.1.22 - 2026-08-19

- Reach 100% line and branch coverage for the firmware, localized-error,
  model-profile, MonitorV2, counter-parsing, and button-migration modules.
- Add regression cases for malformed object-shaped counter data, water-volume
  conversion, undersized monitor packets, empty migration candidates, the base
  model profile, and translated authentication errors.
- Remove an unreachable JSON type check and raise the CI coverage floor from
  40% to 60%; the full suite now contains 193 tests with 61% overall branch
  coverage.

## 1.1.21 - 2026-08-19

- Remove obsolete Eletta command synthesis and structural-frame diagnostics;
  Eletta Explore continues to validate and replay commands learned from the
  official Coffee Link app.
- Stop retaining unused decoded app-command and machine-response snapshots while
  preserving recipe learning, response confirmation, and privacy-safe diagnostics.
- Remove the unused semantic firmware parser; Home Assistant continues to show
  the complete appliance software string reported by the machine.
- Add direct regression coverage for sensor, binary-sensor, and button behavior,
  and keep local review dependencies out of distributable source.

## 1.1.20 - 2026-08-19

- Remove the obsolete `idle` translations again and purge the pre-1.1.18 Last
  Command Status history during the live migration. Future command transitions
  remain recorded normally.

## 1.1.19 - 2026-08-19

- Restore English and Czech translations for the legacy `idle` state so older
  Recorder history displays **No command** / **Žádný příkaz** instead of the raw
  value. The current runtime still starts as unknown and cannot emit `idle`.

## 1.1.18 - 2026-08-19

- Rename **Last Command Result** / **Výsledek posledního příkazu** to the more
  accurate **Last Command Status** / **Stav posledního příkazu** in synchronized
  English and Czech translations.
- Report the command status as unknown after a Home Assistant restart until HA
  actually issues a command, instead of claiming that no command occurred.
- Keep command history meaningful by publishing each transaction transition and
  adding privacy-safe start/completion times and command metadata.
- Prevent Coffee Link app-sniffer data from being mixed into the HA command
  sensor; captured app frames remain available only in diagnostics.

## 1.1.17 - 2026-08-19

- Replace the cloud-status enum with Home Assistant's standard connectivity
  binary sensor, shown as **Cloud Connection** / **Připojení ke cloudu**.
- Rename the exclusive command-session diagnostic to **Coffee Link Session** /
  **Relace Coffee Link** with explicit holder states.
- Remove the ambiguous last-connected timestamp and the cloud-update and
  statistics-sync timestamp entities, including their translations and legacy
  entity-registry entries.
- Stop persisting the removed statistics-sync timestamp; the synchronization
  action itself remains available.

## 1.1.16 - 2026-08-19

- Interpret MonitorV2 byte 6 as an operation-local step instead of a global
  action code, preventing non-milk recipes such as Cold Brew from being shown
  as milk preparation.
- Show status 7 with a non-zero step as the neutral "Preparing beverage" /
  "Připravuje nápoj" state while preserving exact status 10 milk preparation.
- Require status 7 with step 0 before starting a new beverage and retain raw
  status, step, progress, accessory, switch and alarm codes in diagnostics.
- Remove model-dependent water-level and high-alarm interpretations from the
  water-tank entity while retaining verified empty/missing indications.
- Keep English source strings and English/Czech translations synchronized.

## 1.1.15 - 2026-08-18

- Show only the complete appliance firmware identifier in Home Assistant's
  built-in Firmware field, without redundant `SW`/`FW` prefixes.
- Keep the complete ADA connectivity-module firmware separately available in
  privacy-safe diagnostics.

## 1.1.14 - 2026-08-18

- Replace language-specific Device information prefixes with neutral `SW` and
  `FW` labels while retaining both complete manufacturer identifiers.
- Add complete English and Czech translations for all user-visible command and
  service errors.
- Translate dynamically discovered recipe buttons via a placeholder instead of
  exposing a hard-coded English fallback.
- Extend localization regression tests to cover exception keys, runtime entity
  translation keys, and hard-coded Czech text outside `cs.json`.

## 1.1.13 - 2026-08-18

- Label the two complete embedded-software identifiers by component
  ("Coffee maker" and "Connectivity module") instead of implying an
  undocumented firmware-versus-software distinction.

## 1.1.12 - 2026-08-18

- Show both complete software identifiers in the single non-entity Device
  information firmware field, explicitly labelled as appliance software and
  connectivity-module firmware.
- Keep the two source values separately available in diagnostics.

## 1.1.11 - 2026-08-18

- Use the complete appliance `software_version` property as the Home Assistant
  device firmware value instead of Ayla's connectivity-module version.
- Remove the duplicate Software Version sensor; the value is now a non-entity
  fact in Device information and therefore has no click-through or history.
- Keep Ayla/ESP firmware available under an explicit connectivity-module key in
  the privacy-safe diagnostics export.

## 1.1.10 - 2026-08-18

- Present De'Longhi's verbose Eletta build identifier as the concise firmware
  version (`1.1.0`) while safely retaining unknown future formats.
- Exclude the target Home Assistant entity from Recorder so it remains a
  current diagnostic value without unnecessary state history.

## 1.1.9 - 2026-08-18

- Present `d512_percentage_to_deca` as the remaining maintenance interval:
  a raw 21% consumed value is now shown as 79% remaining.
- Rename the entity to "Remaining Until Descale" / "Do odvápnění zbývá" while
  keeping its stable entity identity and the raw alarm threshold unchanged.

## 1.1.8 - 2026-08-18

- Convert Eletta's zero-based `d556_water_hardness` cloud value (0-3) to
  De'Longhi's user-facing levels 1-4, matching the machine display and Coffee
  Link application.
- Reject out-of-range hardness values instead of presenting a misleading
  setting.

## 1.1.7 - 2026-08-18

- Remove the undocumented `d551_cnt_coffee_fondi` raw value from both the
  sensor platform and the waste-container attributes. Its unit and semantics
  are not published, so exposing it as a count was misleading and caused an
  unusable value to be recorded.
- Keep the manufacturer-provided grounds-container percentage and the
  full/missing alarm as the supported user-facing states.

## 1.1.6 - 2026-08-18

- Persist the successful manual statistics-synchronization timestamp in the
  integration's local Home Assistant Store and restore it after restart.
- Keep the existing "Synchronizace statistik" name and retain `unknown` until
  the first successful manual synchronization.

## 1.1.5 - 2026-08-18

- Rename the visible cloud-session states from "Home Assistant" / "Another
  application" to the technically accurate "Active session" / "Other session".
- Keep the existing enum keys for compatibility with entity history and user
  automations; update Czech labels to "Aktivní relace" / "Jiná relace".

## 1.1.4 - 2026-08-18

- Allow up to 20 seconds for beverage acknowledgement after live testing showed
  valid Eletta cloud transitions can arrive after ten seconds.
- Preserve the active beverage after a proven cloud write with late
  acknowledgement, keeping a learned Stop control available as a safety path.

## 1.1.3 - 2026-08-18

- Allow up to 30 seconds for wake and standby acknowledgement while retaining
  the shorter confirmation window for beverage commands.
- Prevent a successful but slower Eletta wake transition from being reported as
  a false command timeout.

## 1.1.2 - 2026-08-18

- Give every beverage button a stable unique ID based on the immutable numeric
  beverage identifier instead of its display or translation key.
- Automatically merge legacy aliases for the same beverage while preserving the
  established entity ID, preventing unavailable duplicates such as Cold Brew.

## 1.1.1 - 2026-08-18

- Accept signed Eletta recipe frames that legitimately omit the optional
  `01 0A` recipe trailer, preserving learned Cappuccino and Cold Brew commands.
- Keep the complete recipe payload when decoding a signed trailerless frame.

## 1.1.0 - 2026-08-18

### Added

- Standalone project identity, original branding and HACS metadata.
- Czech terminology reviewed against Home Assistant naming conventions.
- Filter, descaling, grounds-fill and cloud-session diagnostics.
- Strict validation of learned Eletta command frames.
- Professional documentation, issue forms and validation workflows.

### Changed

- Temporary Gigya/Ayla failures no longer trigger a false credential reauth.
- Cloud authentication is serialized to prevent concurrent login races.
- The data-update timestamp and recipe diagnostic button are disabled by default.
- Recipe diagnostics now log the reported recipe datapoint values, not only names.
- Known learned Cold Brew recipes use translated entity names.

### Fixed

- Water hardness and descale status are no longer classified as cumulative totals.
- Beverage start fails safely when the Eletta monitor state cannot be verified.
- Invalid CRC, recipe identity or device-signature frames are discarded.
- Raw protocol commands require a supported frame type and a valid checksum.
- Czech service selector now uses `Káva` consistently.

## 1.0.0 - 2026-08-18

- Initial standalone version derived from substantially modified MIT-licensed
  Coffee Link integration work.

[Unreleased]: https://github.com/kasiom/ha-delonghi-coffeelink-eletta-explore/compare/v1.3.1...HEAD
[1.3.1]: https://github.com/kasiom/ha-delonghi-coffeelink-eletta-explore/compare/v1.3.0...v1.3.1
[1.3.0]: https://github.com/kasiom/ha-delonghi-coffeelink-eletta-explore/compare/v1.2.1...v1.3.0
[1.3.0-beta.6]: https://github.com/kasiom/ha-delonghi-coffeelink-eletta-explore/compare/v1.2.1...v1.3.0-beta.6
[1.2.1]: https://github.com/kasiom/ha-delonghi-coffeelink-eletta-explore/compare/v1.2.0...v1.2.1
[1.2.0]: https://github.com/kasiom/ha-delonghi-coffeelink-eletta-explore/releases/tag/v1.2.0
