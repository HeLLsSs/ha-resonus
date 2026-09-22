"""
Setting one up: where the library is, which phone to talk to, and the
identifier that phone shows under Settings › Home Assistant.

The library is checked on the way through, since an address or a password
that is wrong here is a browser that stays empty with nothing to say why.
The notify service is checked for existence only: whether the phone answers
is not knowable until something is sent to it.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_PASSWORD, CONF_URL, CONF_USERNAME
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import CONF_NAME, CONF_NOTIFY_SERVICE, CONF_WEBHOOK_ID, DEFAULT_NAME, DOMAIN
from .subsonic import Credentials, SubsonicClient, SubsonicError

SCHEMA = vol.Schema(
    {
        vol.Required(CONF_NAME, default=DEFAULT_NAME): str,
        vol.Required(CONF_URL): str,
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Required(CONF_NOTIFY_SERVICE): str,
        vol.Required(CONF_WEBHOOK_ID): str,
    }
)


class ResonusConfigFlow(ConfigFlow, domain=DOMAIN):
    """One entry per phone."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            url = user_input[CONF_URL].rstrip("/")
            webhook_id = user_input[CONF_WEBHOOK_ID].strip()
            notify_service = user_input[CONF_NOTIFY_SERVICE].strip().removeprefix("notify.")

            await self.async_set_unique_id(webhook_id)
            self._abort_if_unique_id_configured()

            client = SubsonicClient(
                async_get_clientsession(self.hass),
                Credentials(url=url, username=user_input[CONF_USERNAME], password=user_input[CONF_PASSWORD]),
            )
            try:
                await client.ping()
            except SubsonicError:
                errors["base"] = "cannot_connect"
            if not self.hass.services.has_service("notify", notify_service):
                errors[CONF_NOTIFY_SERVICE] = "unknown_notify_service"
            if not errors:
                return self.async_create_entry(
                    title=user_input[CONF_NAME].strip() or DEFAULT_NAME,
                    data={
                        CONF_URL: url,
                        CONF_USERNAME: user_input[CONF_USERNAME],
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                        CONF_NOTIFY_SERVICE: notify_service,
                        CONF_WEBHOOK_ID: webhook_id,
                    },
                )

        return self.async_show_form(step_id="user", data_schema=SCHEMA, errors=errors)
