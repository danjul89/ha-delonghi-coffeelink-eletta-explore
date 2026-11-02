# Usage and safety

## Data updates

After an initial cloud read, the integration receives near-real-time Ayla DSS
updates and performs a full reconciliation poll every five minutes. If the stream
is unavailable or silent, the integration immediately resumes 30-second polling
and reconnects in the background. On a validated Eletta cloud-session profile,
the integration also asks the appliance for a new property snapshot 30 seconds
after startup, once per hour and after every completed beverage, including drinks
prepared at the machine. A refresh is
deferred while the appliance is offline or preparing, another Home Assistant
command is active, or a foreign Coffee Link session is visible.

The disabled diagnostic button **Refresh cloud data** runs the same safe path on
demand: claim or reuse the Coffee Link session, send Coffee Link's `0xe8`
statistics request, wait up to ten seconds for a counter update and reconcile all
properties. It does not wake the machine or prepare a drink. See
[Cloud snapshot refresh](CLOUD_SNAPSHOT_REFRESH.md) for the lifecycle and
diagnostic result meanings.

The Coffee Link account device list is checked every ten minutes. A membership
change schedules one config-entry reload so newly added machines appear and
removed machines do not leave stale devices or entities behind.

## Entities

- **Cloud Connection** is Home Assistant's standard connectivity binary sensor.
- **Machine Status** reports the verified MonitorV2 state and keeps raw status,
  step, progress, accessory and alarm values in attributes for diagnostics.
- **Coffee Link Session** reports whether the exclusive command session is free,
  active under the machine's shared Coffee Link identifier or uses a different
  application identifier. The shared identifier cannot distinguish Home Assistant
  from the official app.
- **Last Command Status** tracks only commands issued by Home Assistant:
  pending, sent, acknowledged, timed out or rejected.
- Beverage and maintenance sensors expose current counters and percentages with
  appropriate units and state classes. Grounds-container percentage is a vendor
  estimate; use the grounds-container problem entity as the authoritative alarm.
- **Wi-Fi Signal Strength** is a disabled-by-default diagnostic sensor. It appears
  only when the vendor cloud supplies RSSI; the Wi-Fi network name is discarded.
- Water tank, grounds container, descaling and filter binary sensors use the
  Home Assistant problem device class, so their normal state is shown as OK.

Diagnostic or developer-only entities, such as **Log recipe data** and **Refresh
cloud data**, are disabled by default and can be enabled from the entity registry
when required.

## Controls

- **Wake** requests a transition from standby.
- **Standby** requests the same state as the physical power control.
- **Refresh cloud data** requests a new appliance snapshot and authoritative
  cloud-property reconciliation. It is disabled by default and intended for
  temporary diagnostics; automatic cooperative refresh normally makes pressing
  it unnecessary.
- **Stop** is available only while the active beverage and its validated Stop
  command are known.
- Beverage buttons replay a validated command learned from Coffee Link.

A greyed-out button is normally an intentional safety state, not a failed entity.

## Learning a recipe

Prepare the recipe once in the official Coffee Link app while Home Assistant is
running. The integration observes, validates and stores the exact frame, then
dynamically adds a button. DSS normally delivers it immediately; during polling
fallback, multiple app commands between two reads can still hide an intermediate
command, so repeat the recipe if needed.

If a command restored from Home Assistant storage no longer passes integrity or
device-signature validation, the integration discards it and creates an item in
**Settings → System → Repairs**. The item explains how to reproduce the affected
commands in Coffee Link and disappears automatically after all of them have been
learned again.

Eletta Explore controls also require a device signature learned from a valid app
frame. Wake, standby and synchronization remain unavailable until that signature
is known.

## Actions

The integration registers `start_beverage`, `stop_beverage` and the
administrator-only `send_raw_command` action. Normal automations should use the
entity buttons or beverage actions. The raw action is intended only for controlled
protocol diagnostics and rejects malformed, unsupported or checksum-invalid
frames. It also enforces the current coffee maker's learned device signature,
accepts only beverage and wake/standby frames, and applies the same readiness,
water-tank and grounds-container checks as the normal beverage actions.

## Automation examples

The following non-dispensing example reports a sustained cloud outage. Replace
the entity and notification target with those from your Home Assistant instance:

```yaml
alias: Coffee maker cloud unavailable
triggers:
  - trigger: state
    entity_id: binary_sensor.eletta_explore_cloud_connection
    to: "off"
    for: "00:05:00"
actions:
  - action: notify.mobile_app_phone
    data:
      message: Coffee Link has been unavailable for five minutes.
mode: single
```

For preparation, prefer a visible Home Assistant button that the user presses
only after checking the cup and accessory. A script can call the integration
action explicitly:

```yaml
sequence:
  - action: ha_delonghi_coffeelink_eletta_explore.start_beverage
    target:
      device_id: YOUR_COFFEE_MAKER_DEVICE_ID
    data:
      beverage: espresso
```

Do not attach preparation to presence, schedules or other unattended triggers.

## Safety rules

- Never start a drink without checking the cup, outlet and required accessory.
- Do not use remote preparation around children, animals or unattended equipment.
- Treat an unavailable control or a rejected pre-brew check as a safety decision.
- Do not bypass safety checks with raw commands.
- The integration cannot confirm every physical condition, including cup
  placement.
