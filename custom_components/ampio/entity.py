"""Base entities for the Ampio integration."""

from __future__ import annotations

from typing import Any

from homeassistant.const import CONF_ICON, CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity import DeviceInfo, Entity

from .const import CONF_STATE_TOPIC, CONF_UNIQUE_ID

CONF_DEVICE = "device"
CONF_FRIENDLY_NAME = "friendly_name"


class AmpioEntity(Entity):
    """Base class for an Ampio entity."""

    _attr_has_entity_name = False
    _attr_should_poll = False

    def __init__(self, config: dict[str, Any]) -> None:
        """Initialize the entity."""
        self._config = config
        self._attr_device_info = DeviceInfo(**config[CONF_DEVICE])
        self._attr_unique_id = config[CONF_UNIQUE_ID]
        self._attr_name = config[CONF_NAME]
        self._attr_icon = config.get(CONF_ICON)
        self._attr_available = False
        self._state: Any = None
        self._sub_state: dict[str, Any] | None = None

    async def subscribe_topics(self) -> None:
        """Subscribe to entity topics."""

    async def async_added_to_hass(self) -> None:
        """Subscribe when the entity is added."""
        await super().async_added_to_hass()
        await self.subscribe_topics()

        registry = er.async_get(self.hass)
        if (
            self.registry_entry is not None
            and self.registry_entry.name is None
            and (friendly_name := self._config.get(CONF_FRIENDLY_NAME))
        ):
            registry.async_update_entity(self.entity_id, name=friendly_name)
        self._attr_available = True
        self.async_write_ha_state()

    @property
    def extra_state_attributes(self) -> dict[str, str] | None:
        """Return Ampio diagnostic state attributes."""
        state_topic = self._config.get(CONF_STATE_TOPIC)
        if not state_topic:
            return None
        parts = state_topic.split("/")
        if len(parts) < 4:
            return None
        return {"ampio_topic": f"{parts[-4].lower()}/{parts[-2]}/{parts[-1]}"}

    @callback
    def _mark_available(self) -> None:
        """Mark the entity available after receiving a message."""
        self._attr_available = True
