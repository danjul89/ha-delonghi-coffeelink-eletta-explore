# Compatibility and known limitations

## Development validation targets

The current development CI tests the actual Home Assistant 2026.8.2 and
2026.10.4 runtimes independently on Ubuntu, including configuration, password
reconfiguration, setup/unload and schema validation. The supported minimum
remains 2026.8.2. Static typing follows the current target's Probatio API; the
runtime uses HA's backwards-compatible validation import. These maintenance
checks do not change appliance protocol behavior or broaden model support.

## Support matrix

The unreleased statistics candidate (planned 1.3.2-beta.1) incorporates PR #16's
Coffee Link `0xe8 0xf0` request, a single 45-second verification deadline and
serialized statistics requests. Its live-monitor completion trigger depends on
observing an accepted DSS transition; hourly refresh remains the fallback.
The byte layout matches Coffee Link 4.9.6 and automated tests cover both HA
targets, but a backed-up beta deployment and physical statistics acceptance on
the user's Eletta are still pending. This does not broaden model support or
replace the published 1.3.1 release's acceptance evidence.

| Model/profile | Cloud channel | Status |
|---|---|---|
| Eletta Explore ECAM450.65.G (`DL-striker-cb`) | EU Coffee Link/Ayla | Confirmed development and live-test target |
| PrimaDonna Soul (`DL-millcore`) | Coffee Link/Ayla | Experimental; retained profile, incomplete physical acceptance |
| Other models | Unknown/model-dependent | Unsupported unless validated with sanitized diagnostics and physical tests |

The 1.2.x line is tested against the actual Home Assistant 2026.8.2 runtime
interfaces. Version 1.2.0 completed deployment, clean-restart and supervised
physical acceptance on the Eletta Explore listed above. Version 1.2.1 changes
distribution metadata and documentation without changing beverage-command or
machine-state behavior; it has since been installed through HACS and verified to
load on the same target Home Assistant. Newer Home Assistant versions are
expected to work, but vendor and Home Assistant changes require continuing
validation.

Local beta 1.3.0-beta.4 completed automated verification, a backed-up live
deployment, Home Assistant configuration validation, a clean restart and
read-only acceptance on the same Eletta Explore. The Ayla DSS stream was active,
received three real events during a statistics synchronization and reported no
current error. Loaded English and Czech resources were complete, all maintenance
sensors settled to available, and the machine remained in standby. Its aggregate
statistics matched Coffee Link (639 black coffees, 308 milk drinks, 10 cold milk
drinks and 16 Mug to Go), while the corrected water total reported 209.925 L.

Release candidate 1.3.0-beta.5 preserves those verified Eletta formulas and adds
the legacy Coffee Link formula used by the PrimaDonna Soul profile: `d700` is
black coffee and
`d701 + d703` is the milk-beverage summary. It no longer labels `d703` as water.
Unknown OEM models expose only unambiguous direct counters until a model-specific
profile is supported. Per-recipe counters remain opt-in for newly registered
entities; existing registry choices are preserved. Beta.5 also discards the
local IP address received from the vendor cloud instead of retaining or exposing
it, makes account reconfiguration password-only, and aligns English names and
De'Longhi branding. Its isolated and actual-Home-Assistant test suites pass.
Beta.5 also completed backed-up deployments, configuration checks, clean
restarts, read-only acceptance and a supervised physical cycle on the verified
Eletta. Wake passed from standby through waking to ready, Cold Brew Start/Stop
returned safely to ready, and Standby returned the machine to standby. The DSS
stream remained healthy and all four maintenance-condition entities were
available without manual synchronization. The Eletta command property declares
`ack_enabled: false`; therefore Coffee Link and the integration confirm commands
from resulting cloud state rather than waiting for a nonexistent datapoint ACK.
The live stream received datapoint events and no datapoint-ACK event, exactly as
declared. No beta.5 release has been published.

Release candidate 1.3.0-beta.6 keeps the beta.5 protocol and model mappings and
tightens runtime reliability, rate-limit handling, command-state confirmation,
account-device caching and code quality. It completed a backed-up deployment,
Home Assistant configuration validation, a clean restart and read-only cloud
synchronization on the same Eletta. The DSS stream recovered from the expected
post-restart polling fallback, received real datapoint events and remained
healthy. A supervised Wake, Cold Brew Start/Stop and Standby cycle then passed;
every command was attributed to Home Assistant and confirmed by the resulting
machine state, as required by Eletta's non-ACK command property. The machine
returned to standby and the Home Assistant system log contained no integration
error.

Candidate 1.3.0-beta.7 keeps the physically verified beta.6 protocol and model
mappings unchanged. Its diagnostic-button naming, entity defaults and
documentation changes do not broaden the compatibility claim; beta.6 remains
the supervised physical-command baseline.

Candidate 1.3.0-beta.8 changes only cloud-session recovery. It does not alter
device discovery, model profiles, property mappings, learned recipes or command
frames. A rejected short-lived Ayla token is renewed and its refused request is
replayed once, while only a direct saved-password rejection can request Home
Assistant reauthentication. The same compatibility boundaries therefore apply.

Stable 1.3.0 promotes the validated 1.3.0-beta.9 cloud-snapshot lifecycle on
Eletta profiles. Coffee Link's `03 02` device refresh is sent cooperatively rather than
holding the session continuously: after startup, hourly and after a completed
beverage command. It is skipped while the appliance is busy, offline or visibly
owned by a foreign session. Profiles without the Eletta cloud-session signature
retain read-only property reconciliation and are not sent this model-specific
automatic request. The exact candidate passed a backed-up deployment, clean
restart and unattended startup refresh on the verified Eletta: four DSS events
were received, diagnostics reported `completed_unchanged`, the machine remained
in standby and the current filter counters were preserved. Counter mappings and
compatibility claims are unchanged.

Stable 1.3.1 changes only DSS reconnect diagnostics and rate-limit timing. It
honors a positive vendor `Retry-After` interval without shortening the existing
backoff and reports the failing connection phase and HTTP status without private
exception text. The exact prerelease was installed through HACS on Home Assistant
2026.9.4 and kept the verified Eletta online and streaming; its Coffee Link
session returned automatically from active to free after the normal five-minute
window. No appliance command, entity mapping or compatibility boundary changed.

## Verified Eletta behavior

- Account setup, reauthentication, hybrid DSS/polling and cloud-outage recovery
  logic.
- Machine, counter and maintenance-state parsing.
- Dynamic recipe learning and stable button identity.
- Wake and standby transitions.
- Cold Brew start and safe Stop on the physical machine.
- Coffee Link session ownership and command acknowledgement handling.
- English/Czech translation-key and placeholder parity.

Wake, standby and Cold Brew Start/Stop were physically repeated on beta.6. Last
Command Status recorded the expected transaction transitions, used the friendly
Cold Brew name for Start and Stop, and the machine returned to standby. Other
beverage recipes have not all completed the same supervised physical matrix.

## Known limitations

- The vendor provides no public supported API for this integration.
- Operation requires internet access and availability of the vendor cloud.
- Vendor authentication, cloud-property or mobile-app changes may require an
  integration update.
- Eletta recipe controls must normally be observed once in Coffee Link.
- While DSS is unavailable, multiple app actions between two 30-second fallback
  polls can cause an intermediate command to be missed.
- Account membership is checked every ten minutes. Adding or removing a coffee
  maker triggers an automatic integration reload; the change is therefore not
  instantaneous.
- The integration cannot verify cup placement or every accessory condition.
- A command accepted by the cloud can be acknowledged later than the local timeout.
  Stop remains available when the property write is known to have succeeded.
- PrimaDonna Soul and unknown models must not be described as fully supported
  without model-specific evidence.

Compatibility reports should include the commercial model, internal OEM model,
cloud region, Home Assistant and integration versions, exact steps and sanitized
integration diagnostics.
