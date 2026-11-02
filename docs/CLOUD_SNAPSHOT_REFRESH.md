# Cloud snapshot refresh

## Why it exists

Ayla stores the most recently published appliance properties. Polling or DSS can
read and accelerate changes in that cloud copy, but neither mechanism alone asks
the coffee maker to publish a new statistics snapshot. Coffee Link 4.9.6 sends a
`0xe8 0xf0` statistics request when its statistics view is opened; the appliance
answers by uploading its changed `d5*`/`d7*` counters, also from standby. The
`03 02` session refresh that the app sends in the same session only republishes
`d302` and leaves the counters untouched.

The integration uses the same request cooperatively on validated Eletta
cloud-session profiles. This prevents counters such as filter usage and filtered
water volume from depending on a later launch of the mobile app.

## Lifecycle

- The first automatic request is scheduled 30 seconds after startup.
- A successful request is repeated at most once per hour.
- A completed beverage command schedules another request when the machine is no
  longer preparing.
- A beverage prepared at the machine itself schedules a request eight seconds
  after an accepted live DSS monitor transition from preparing to ready. If that
  transition is missed or DSS is unavailable, the periodic refresh remains the
  fallback; an immediate refresh after every drink is not guaranteed.
- A skipped or failed automatic request is eligible for retry after five minutes.
- The integration checks the live `app_id` before claiming a session. It does not
  take over a visibly foreign session and does not maintain Coffee Link's
  foreground 140-second keepalive loop.

The request is not a wake or beverage command. It is deferred while the coffee
maker is offline, is preparing a drink, or another Home Assistant command is in
progress. Unsupported or unsigned model profiles continue to use read-only cloud
reconciliation without receiving this Eletta-specific frame.

Only one statistics request can be in flight. Another automatic request is
deferred without replacing the active diagnostics; a concurrent manual request
reports that an operation is in progress. The statistics wait does not hold the
normal appliance-command lock.

## Verification

After sending the request, the integration waits within one 45-second deadline
for a changed counter snapshot, then performs an authoritative full-property
read. Responses taking 17-24 seconds were reported on an Eletta; this is not a
guaranteed response time for every firmware. An unchanged event does not finish
the wait early or restart the deadline. Settings such as water hardness and
software-version properties do not count as statistics updates.

The integration compares a private digest of recognized maintenance/beverage
counter values and cloud update timestamps. The
digest, property values, device identifier and command frame are never included
in diagnostics.

Downloadable diagnostics expose only:

- attempt and success counts;
- last attempt/success UTC times;
- trigger (`automatic`, `post_command`, `beverage_finished` or `manual`);
- result (`completed_updated`, `completed_unchanged`, `completed_unverified`,
  `skipped_*` or `failed*`);
- an exact DSS ACK status when the device property declares ACK support.

`completed_updated` means that the observed snapshot changed; it does not prove
that every individual counter was refreshed. `completed_unchanged` means that a
relevant DSS publication was observed but the final snapshot stayed the same.
`completed_unverified` means that no comparable baseline or fresh publication
could be established within the verification window. It is not a command
rejection and does not by itself prove the counters are stale. A device may send
only changed values. Later DSS updates are still applied, without retrospectively
claiming that they were caused by an earlier request. A success count measures
completed request/reconciliation cycles, not guaranteed counter freshness.
These verification meanings describe the Eletta appliance-request path. Legacy
profiles perform read-only reconciliation and report the cloud comparison.

These are runtime diagnostics, not Home Assistant entities, and therefore do not
create recorder history. Automatic refresh also does not change **Last Command
Status**, which remains reserved for appliance commands explicitly issued by a
Home Assistant user or automation.

## Manual diagnostic button

**Refresh cloud data** uses the same implementation and is disabled by default.
Enable it temporarily only when diagnosing stale values. A completed unchanged
result is valid when the coffee maker republishes the same values; it does not by
itself indicate a fault.
