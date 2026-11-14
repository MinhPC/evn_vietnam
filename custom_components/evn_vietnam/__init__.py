from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from . import evn_core
from .const import DATA_DEVICE, DOMAIN
from .sensor import EVNDevice

PLATFORMS = ["sensor", "binary_sensor", "button"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Establish connection with EVN Cloud."""
    entry_config = hass.data.setdefault(DOMAIN, {}).setdefault(entry.entry_id, {})
    entry_config.update(entry.data)

    # Tạo device + coordinator một lần, dùng chung cho mọi platform.
    evn_device = EVNDevice(entry_config, evn_core.EVNAPI(hass, True))
    try:
        await evn_device.async_create_coordinator(hass, entry)
    except Exception:
        hass.data[DOMAIN].pop(entry.entry_id, None)
        raise
    entry_config[DATA_DEVICE] = evn_device

    # Đổi options (chu kỳ cập nhật) hoặc data (reauth) -> tải lại entry
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry."""
    await hass.config_entries.async_reload(entry.entry_id)
