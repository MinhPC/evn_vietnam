"""Config flow for EVN Data integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult

from . import evn_core
from .const import (
    CONF_AREA,
    CONF_CUSTOMER_ID,
    CONF_ERR_UNKNOWN,
    CONF_MONTHLY_START,
    CONF_PASSWORD,
    CONF_SUCCESS,
    CONF_USERNAME,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

def _required(key: str, data: dict[str, Any]) -> vol.Required:
    """vol.Required kèm default nếu người dùng đã nhập trước đó."""
    if data.get(key) is None:
        return vol.Required(key)
    return vol.Required(key, default=data[key])


def CUSTOMER_ID_FIELD(data: dict[str, Any]) -> dict:
    return {
        _required(CONF_CUSTOMER_ID, data): vol.All(str, vol.Length(min=11, max=13))
    }


def AUTH_FIELD(data: dict[str, Any]) -> dict:
    return {
        _required(CONF_USERNAME, data): str,
        _required(CONF_PASSWORD, data): str,
    }

DATE_START_FIELD = {
    vol.Required(CONF_MONTHLY_START, default=24): vol.All(int, vol.Range(min=1, max=28))
}


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the Config Flow for setting up this Integration."""

    VERSION = 1

    def __init__(self):
        self._user_data = {}
        self._api = None
        self._errors = {}

    async def async_step_fulfill_data(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle Fulfill Data config flow by the user."""

        self._errors = {}

        if user_input is not None:

            self._user_data.update(user_input)
            self._api = evn_core.EVNAPI(self.hass, True)

            verify_account = await self._try_auth()

            if verify_account != CONF_SUCCESS:
                self._errors["base"] = verify_account
            else:
                verify_id = await self._verify_id()

                if verify_id != CONF_SUCCESS:
                    self._errors["base"] = verify_id
                else:
                    await self.async_set_unique_id(self._user_data[CONF_CUSTOMER_ID])

                    self._abort_if_unique_id_configured()

                    return self.async_create_entry(
                        title=self._user_data[CONF_CUSTOMER_ID], data=self._user_data
                    )

        data_schema = AUTH_FIELD(self._user_data)

        if self._errors:
            data_schema |= CUSTOMER_ID_FIELD(self._user_data)

        if self._user_data[CONF_AREA].get("date_needed"):
            data_schema |= DATE_START_FIELD

        return self.async_show_form(
            step_id="fulfill_data",
            data_schema=vol.Schema(data_schema),
            errors=self._errors,
            description_placeholders={
                "customer_id": self._user_data[CONF_CUSTOMER_ID],
                "evn_name": self._user_data[CONF_AREA].get("name"),
            },
        )

    async def async_step_evn_info(self, user_input=None):
        """Handle EVN-info config flow by the user."""
        if user_input is not None:
            return await self.async_step_fulfill_data()

        self._errors = {}

        branches = await evn_core.async_load_evn_branches(self.hass)
        evn_info = evn_core.get_evn_info_sync(
            self._user_data[CONF_CUSTOMER_ID], branches
        )

        if evn_info.get("status") == CONF_SUCCESS:
            self._user_data[CONF_AREA] = evn_info["evn_area"]

            return self.async_show_form(
                step_id="evn_info",
                description_placeholders=evn_info,
                errors=self._errors,
            )
        else:
            return self.async_abort(
                reason=evn_info.get("status"), description_placeholders=evn_info
            )

    async def async_step_customer_id(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle customer-id config flow by the user."""

        if user_input is not None:
            self._user_data[CONF_CUSTOMER_ID] = user_input[CONF_CUSTOMER_ID].upper()
            return await self.async_step_evn_info()

        return self.async_show_form(
            step_id="customer_id",
            data_schema=vol.Schema(CUSTOMER_ID_FIELD(self._user_data)),
            errors=self._errors,
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle a flow initialized by the user."""
        return await self.async_step_customer_id()

    async def _try_auth(self):
        """Try authenticating credentials given by the user config flow."""

        try:
            res = await self._api.login(
                self._user_data.get(CONF_AREA),
                self._user_data.get(CONF_USERNAME),
                self._user_data.get(CONF_PASSWORD),
                self._user_data.get(CONF_CUSTOMER_ID),
            )
        except Exception as e:
            _LOGGER.exception("Unexpected exception: %s", e)
            return CONF_ERR_UNKNOWN

        return res

    async def _verify_id(self):
        """Try verifying EVN Customer ID given by the user config flow."""

        try:
            res = await self._api.request_update(
                self._user_data.get(CONF_AREA),
                self._user_data.get(CONF_USERNAME),
                self._user_data.get(CONF_PASSWORD),
                self._user_data.get(CONF_CUSTOMER_ID),
                self._user_data.get(CONF_MONTHLY_START),
            )
        except Exception as e:
            _LOGGER.exception("Unexpected exception: %s", e)
            return CONF_ERR_UNKNOWN

        return res["status"]
