# Contributing

Thank you for helping improve the integration.

## Before opening an issue

1. Update Home Assistant and the integration to supported versions.
2. Restart Home Assistant and reproduce the problem once.
3. Download integration diagnostics from **Settings → Devices & services**.
4. Check existing issues and the troubleshooting guide.

Never publish a Coffee Link password, access/refresh token, e-mail address, DSN,
device serial number or a raw learned command frame. The issue form asks for
sanitized diagnostics only.

## Pull requests

- Keep changes focused and explain user-visible behavior.
- Add or update tests for every behavior change.
- Update the complete runtime files `translations/en.json` and
  `translations/cs.json` together; do not add a Core build-source
  `strings.json` file to this custom integration.
- Keep line and branch coverage at 100%.
- Update `CHANGELOG.md` for user-visible changes.
- Do not introduce network calls at module import time.
- Do not claim support for a model without reproducible test evidence.

## Local validation

Use Python 3.14 and run the same checks as CI:

```shell
python -m pip install --requirement requirements_test.txt
python -m compileall -q custom_components tests tests_ha
python -m ruff check custom_components tests tests_ha
python -m ruff format --check custom_components tests tests_ha
python -m pytest -q \
  --cov=custom_components/ha_delonghi_coffeelink_eletta_explore \
  --cov-report=term-missing \
  --cov-fail-under=100
```

The runtime CI matrix uses Python 3.14.2 and executes `tests_ha` independently
against the minimum supported Home Assistant 2026.8.2
(`requirements_ha_test_minimum.txt`) and current validation target 2026.10.4
(`requirements_ha_test.txt`). Strict mypy runs against the current target only.
This verifies public Home Assistant interfaces and schema compatibility in
addition to the fast isolated suite. Use a separate virtual environment for
each requirement file; do not combine them with `requirements_test.txt`, since
the Home Assistant helper pins its own pytest and coverage versions.

On Linux, run the current target as follows:

```shell
python -m pip install --requirement requirements_ha_test.txt
python -m mypy custom_components/ha_delonghi_coffeelink_eletta_explore
python -m pytest -q -c pytest_ha.ini
```

For the minimum target, install `requirements_ha_test_minimum.txt` in another
environment and run the same pytest command, without mypy. Newer HA test plugins
import Linux-only modules such as `fcntl`; use the Ubuntu GitHub Actions jobs
when developing on Windows rather than mocking platform modules.

Runtime schemas keep the `voluptuous` import supported by both HA generations.
Only static checking uses Probatio's types, matching the current HA API without
requiring Probatio on older installations. Do not suppress schema errors or
raise the minimum HA version merely to make an updated test tool pass.

Tests are deterministic and must not contact a real Coffee Link account, coffee
maker or external service. Sanitize every fixture and captured protocol sample.
Replace device signatures and other identifiers with documented deterministic
synthetic bytes before committing a protocol frame.

The maintainer may request a physical verification because the cloud protocol is
proprietary and some operations dispense hot liquids.
