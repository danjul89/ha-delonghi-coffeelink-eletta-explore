"""Config flow for the De'Longhi Coffee Link – Eletta Explore integration."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .ayla_client import AuthError, AylaDevice, CloudError, DelonghiAylaClient
from .const import CONF_EMAIL, CONF_PASSWORD, DOMAIN

if TYPE_CHECKING:
    # Current HA types refer to Probatio; at runtime HA supplies the compatible
    # voluptuous alias, which also keeps older supported releases working.
    import probatio as vol
else:
    import voluptuous as vol

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): str,
        vol.Required(CONF_PASSWORD): str,
    }
)
STEP_REAUTH_SCHEMA = vol.Schema({vol.Required(CONF_PASSWORD): str})


class DelonghiConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle initial setup and credential reauthentication."""

    VERSION = 1

    async def _async_validate_account(self, email: str, password: str) -> tuple[str | None, list[AylaDevice] | None]:
        """Validate credentials and return an error key plus discovered devices."""
        client = DelonghiAylaClient(async_get_clientsession(self.hass), email.strip(), password)
        try:
            await client.async_authenticate()
            devices = await client.async_get_devices()
        except AuthError:
            return "invalid_auth", None
        except CloudError:
            return "cannot_connect", None
        except Exception:
            _LOGGER.exception("Unexpected Coffee Link validation error")
            return "unknown", None
        if not devices:
            return "no_devices", None
        return None, devices

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Create a config entry after testing the account."""
        errors: dict[str, str] = {}
        if user_input is not None:
            email = user_input[CONF_EMAIL].strip()
            error, _devices = await self._async_validate_account(email, user_input[CONF_PASSWORD])
            if error:
                errors["base"] = error
            else:
                await self.async_set_unique_id(email.casefold())
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title="De'Longhi Coffee Link – Eletta Explore",
                    data={
                        CONF_EMAIL: email,
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_SCHEMA,
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """Start reauthentication for an existing entry."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Validate and save a replacement password without duplicating the entry."""
        reauth_entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            error, _devices = await self._async_validate_account(reauth_entry.data[CONF_EMAIL], user_input[CONF_PASSWORD])
            if error:
                errors["base"] = error
            else:
                await self.async_set_unique_id(reauth_entry.data[CONF_EMAIL].casefold())
                self._abort_if_unique_id_mismatch()
                return self.async_update_reload_and_abort(
                    reauth_entry,
                    data_updates={CONF_PASSWORD: user_input[CONF_PASSWORD]},
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=STEP_REAUTH_SCHEMA,
            errors=errors,
            description_placeholders={"email": reauth_entry.data[CONF_EMAIL]},
        )

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Update credentials for the existing Coffee Link account."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            error, _devices = await self._async_validate_account(entry.data[CONF_EMAIL], user_input[CONF_PASSWORD])
            if error:
                errors["base"] = error
            else:
                await self.async_set_unique_id(entry.data[CONF_EMAIL].casefold())
                self._abort_if_unique_id_mismatch()
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={CONF_PASSWORD: user_input[CONF_PASSWORD]},
                    reason="reconfigure_successful",
                )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=STEP_REAUTH_SCHEMA,
            errors=errors,
            description_placeholders={"email": entry.data[CONF_EMAIL]},
        )
