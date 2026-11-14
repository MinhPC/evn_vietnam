"""Binary sensor: trạng thái lịch cắt điện (chỉ khu vực có API lịch cắt điện)."""

from datetime import datetime, timedelta, timezone

from homeassistant.components.binary_sensor import (
    DOMAIN as ENTITY_DOMAIN,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_AREA,
    CONF_SUCCESS,
    DATA_DEVICE,
    DOMAIN,
    ID_OUTAGE_ACTIVE,
    ID_OUTAGE_SOON,
    ID_OUTAGE_WINDOWS,
    OUTAGE_SOON_WINDOW_HOURS,
)

_VN_TZ = timezone(timedelta(hours=7))
_REFRESH_EVERY = timedelta(minutes=1)

# key -> (tên hiển thị, icon)
_SENSORS = {
    ID_OUTAGE_SOON: ("Sắp cắt điện", "mdi:transmission-tower-off"),
    ID_OUTAGE_ACTIVE: ("Đang cắt điện", "mdi:flash-off"),
}


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
):
    """Setup the binary sensor platform."""
    entry_config = hass.data[DOMAIN][entry.entry_id]
    evn_area = entry_config.get(CONF_AREA) or {}
    if not evn_area.get("evn_loadshedding_url"):
        return

    device = entry_config[DATA_DEVICE]
    async_add_entities(EVNOutageBinarySensor(device, key) for key in _SENSORS)


class EVNOutageBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """On/off theo lịch cắt điện, so sánh với giờ hiện tại mỗi phút."""

    def __init__(self, device, key: str) -> None:
        super().__init__(device.coordinator)
        self._device = device
        self._key = key
        name, icon = _SENSORS[key]
        self._attr_name = f"{device.name} {name}"
        self._attr_icon = icon
        self._attr_unique_id = f"{device.customer_id}_{key}".lower()
        self._attr_device_info = device.device_info
        self.entity_id = f"{ENTITY_DOMAIN}.{self._attr_unique_id}"

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()

        # Coordinator chỉ cập nhật mỗi vài giờ; trạng thái phải đổi đúng giờ.
        @callback
        def _tick(_now) -> None:
            self.async_write_ha_state()

        self.async_on_remove(
            async_track_time_interval(self.hass, _tick, _REFRESH_EVERY)
        )

    def _windows(self) -> list[tuple[datetime, datetime]]:
        return self._device.data.get(ID_OUTAGE_WINDOWS) or []

    @property
    def available(self) -> bool:
        return self._device.data.get("status") == CONF_SUCCESS

    @property
    def is_on(self) -> bool:
        now = datetime.now(_VN_TZ)
        if self._key == ID_OUTAGE_ACTIVE:
            return any(start <= now < end for start, end in self._windows())
        soon = now + timedelta(hours=OUTAGE_SOON_WINDOW_HOURS)
        return any(now < start <= soon for start, _ in self._windows())

    @property
    def extra_state_attributes(self) -> dict:
        now = datetime.now(_VN_TZ)
        upcoming = [w for w in self._windows() if w[1] > now]
        if not upcoming:
            return {}
        start, end = min(upcoming)
        return {"start": start.isoformat(), "end": end.isoformat()}
