"""Button: cập nhật dữ liệu EVN ngay lập tức."""

import time

from homeassistant.components.button import DOMAIN as ENTITY_DOMAIN, ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DATA_DEVICE, DOMAIN, ID_REFRESH

# Tránh người dùng bấm liên tục làm EVN chặn tài khoản/IP
MIN_REFRESH_INTERVAL = 60  # giây


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
):
    """Setup the button platform."""
    device = hass.data[DOMAIN][entry.entry_id][DATA_DEVICE]
    async_add_entities([EVNRefreshButton(device)])


class EVNRefreshButton(ButtonEntity):
    """Nút làm mới dữ liệu."""

    _attr_icon = "mdi:refresh"

    def __init__(self, device) -> None:
        self._device = device
        self._last_press = 0.0
        self._attr_name = f"{device.name} Cập nhật ngay"
        self._attr_unique_id = f"{device.customer_id}_{ID_REFRESH}".lower()
        self._attr_device_info = device.device_info
        self.entity_id = f"{ENTITY_DOMAIN}.{self._attr_unique_id}"

    async def async_press(self) -> None:
        now = time.monotonic()
        if now - self._last_press < MIN_REFRESH_INTERVAL:
            return
        self._last_press = now
        await self._device.coordinator.async_request_refresh()
