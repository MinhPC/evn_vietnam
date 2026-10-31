"""Setup and manage HomeAssistant Entities."""

import logging
from typing import Any

from homeassistant.components.sensor import (
    DOMAIN as ENTITY_DOMAIN,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from . import evn_core
from .const import (
    CONF_AREA,
    CONF_CUSTOMER_ID,
    CONF_DEVICE_MANUFACTURER,
    CONF_DEVICE_MODEL,
    CONF_DEVICE_NAME,
    CONF_DEVICE_SW_VERSION,
    CONF_ERR_INVALID_AUTH,
    CONF_MONTHLY_START,
    CONF_PASSWORD,
    CONF_SUCCESS,
    CONF_USERNAME,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    ID_LOADSHEDDING,
)
from .types import EVN_SENSORS, EVNSensorEntityDescription

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
):
    """Setup the sensor platform."""

    entry_config = hass.data[DOMAIN][entry.entry_id]

    evn_api = evn_core.EVNAPI(hass, True)
    evn_device = EVNDevice(entry_config, evn_api)

    await evn_device.async_create_coordinator(hass, entry)

    # Chỉ khu vực có API lịch cắt điện (hiện tại: EVNSPC) mới tạo sensor này
    evn_area = entry_config.get(CONF_AREA) or {}
    supports_loadshedding = bool(evn_area.get("evn_loadshedding_url"))

    descriptions = [
        description
        for description in EVN_SENSORS
        if description.key != ID_LOADSHEDDING or supports_loadshedding
    ]

    # Dọn entity cũ không còn được tạo (vd loadshedding ở khu vực không hỗ trợ)
    # để tránh entity mồ côi hiển thị "Unavailable".
    created_unique_ids = {
        f"{evn_device.customer_id}_{description.key}".lower()
        for description in descriptions
    }
    registry = er.async_get(hass)
    for reg_entry in er.async_entries_for_config_entry(registry, entry.entry_id):
        if reg_entry.unique_id not in created_unique_ids:
            registry.async_remove(reg_entry.entity_id)

    async_add_entities(
        EVNSensor(evn_device, description) for description in descriptions
    )


class EVNDevice:
    """EVN Device Instance"""

    def __init__(self, dataset, api: evn_core.EVNAPI) -> None:
        """Construct Device wrapper."""
        self.hass = api.hass
        self._api = api
        self._coordinator: DataUpdateCoordinator | None = None

        self.customer_id = dataset.get(CONF_CUSTOMER_ID)
        self.name = f"{CONF_DEVICE_NAME}: {self.customer_id}"
        self._username = dataset.get(CONF_USERNAME)
        self._password = dataset.get(CONF_PASSWORD)
        self._area = dataset.get(CONF_AREA)
        self._monthly_start = dataset.get(CONF_MONTHLY_START)

        self.data: dict[str, Any] = {}
        self.device_info: DeviceInfo | None = None

    async def _async_build_device_info(self) -> None:
        """Tính DeviceInfo một lần (tra chi nhánh trong evn_branches.json)."""
        branches = await evn_core.async_load_evn_branches(self.hass)
        hw_version = f"by {self._area['name']}"

        if branches:
            evn_info = evn_core.get_evn_info_sync(self.customer_id, branches)
            if (
                evn_info["status"] == CONF_SUCCESS
                and evn_info["evn_branch"] != "Unknown"
            ):
                hw_version = f"by {evn_info['evn_branch']}"

        self.device_info = DeviceInfo(
            name=self.name,
            identifiers={(DOMAIN, self.customer_id)},
            manufacturer=CONF_DEVICE_MANUFACTURER,
            sw_version=CONF_DEVICE_SW_VERSION,
            hw_version=hw_version,
            model=CONF_DEVICE_MODEL,
        )

    async def _async_request(self) -> dict[str, Any]:
        return await self._api.request_update(
            self._area,
            self._username,
            self._password,
            self.customer_id,
            self._monthly_start,
        )

    async def update(self) -> dict[str, Any]:
        """Update device data from EVN Endpoints."""

        self.data = await self._async_request()

        if self.data.get("status") == CONF_ERR_INVALID_AUTH:
            _LOGGER.info(
                "[EVN ID %s] Expired session, try reauthenticating.",
                self.customer_id,
            )

            login_state = await self._api.login(
                self._area, self._username, self._password, self.customer_id
            )

            if login_state == CONF_SUCCESS:
                self.data = await self._async_request()

        if self.data.get("status") == CONF_SUCCESS:
            _LOGGER.debug(
                "[EVN ID %s] Successfully fetched new data from EVN Server.",
                self.customer_id,
            )
        else:
            _LOGGER.warning(
                "[EVN ID %s] Could not fetch new data - %s",
                self.customer_id,
                self.data.get("data"),
            )

        return self.data

    async def async_create_coordinator(
        self, hass: HomeAssistant, entry: ConfigEntry
    ) -> None:
        """Create the coordinator for this specific device."""
        if self._coordinator:
            return

        await self._async_build_device_info()

        coordinator = DataUpdateCoordinator(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN}-{self.customer_id}",
            update_method=self.update,
            update_interval=DEFAULT_SCAN_INTERVAL,
        )
        await coordinator.async_config_entry_first_refresh()
        self._coordinator = coordinator

    @property
    def coordinator(self) -> DataUpdateCoordinator | None:
        """Return coordinator associated."""
        return self._coordinator


class EVNSensor(CoordinatorEntity, SensorEntity):
    """EVN Sensor Instance."""

    entity_description: EVNSensorEntityDescription

    def __init__(self, device: EVNDevice, description: EVNSensorEntityDescription):
        """Construct EVN sensor wrapper."""
        super().__init__(device.coordinator)

        self._device = device
        self._default_name = description.name
        self.entity_description = description

        self._attr_name = f"{device.name} {description.name}"
        self._attr_unique_id = f"{device.customer_id}_{description.key}".lower()
        self._attr_device_info = device.device_info
        self.entity_id = f"{ENTITY_DOMAIN}.{self._attr_unique_id}"

    def _current(self) -> dict | None:
        """Dữ liệu {"value", "info"} hiện tại của sensor này."""
        data = self.entity_description.value_fn(self._device.data)
        return data if isinstance(data, dict) else None

    @property
    def native_value(self):
        """Return the state of the sensor."""
        data = self._current()

        if data is None:
            return None

        if self.entity_description.dynamic_name:
            self._attr_name = f"{self._default_name} {data.get('info')}"

        if self.entity_description.dynamic_icon:
            self._attr_icon = data.get("info")

        return data.get("value")

    @property
    def available(self) -> bool:
        """Return the availability of the sensor."""
        if self._device.data.get("status") != CONF_SUCCESS:
            return False
        data = self._current()
        return data is not None and data.get("value") is not None

    @property
    def last_reset(self):
        if self.entity_description.state_class == SensorStateClass.TOTAL:
            data = self._current()
            return data.get("info") if data else None

        return None
