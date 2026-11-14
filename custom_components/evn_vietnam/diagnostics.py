"""Diagnostics: xuất dữ liệu hỗ trợ gỡ lỗi, đã che thông tin nhạy cảm."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    CONF_CUSTOMER_ID,
    CONF_PASSWORD,
    CONF_USERNAME,
    DATA_DEVICE,
    DOMAIN,
    ID_OUTAGE_WINDOWS,
)

TO_REDACT = {CONF_USERNAME, CONF_PASSWORD, CONF_CUSTOMER_ID}


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    device = hass.data.get(DOMAIN, {}).get(entry.entry_id, {}).get(DATA_DEVICE)
    data = dict(device.data) if device else {}
    data.pop(ID_OUTAGE_WINDOWS, None)  # đã có sensor tương ứng, tránh dư thừa

    return {
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        "options": dict(entry.options),
        "last_update_success": (
            device.coordinator.last_update_success if device else None
        ),
        "data": async_redact_data(_jsonable(data), TO_REDACT),
    }
