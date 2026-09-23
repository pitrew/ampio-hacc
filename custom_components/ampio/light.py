"""Ampio light entities."""

from __future__ import annotations

import functools

from homeassistant.components import light
from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_RGB_COLOR,
    ATTR_RGBW_COLOR,
    ColorMode,
    LightEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import discovery, subscription
from .client import async_publish
from .const import (
    CONF_BRIGHTNESS_COMMAND_TOPIC,
    CONF_BRIGHTNESS_STATE_TOPIC,
    CONF_COMMAND_TOPIC,
    CONF_RGB_COMMAND_TOPIC,
    CONF_RGB_STATE_TOPIC,
    CONF_STATE_TOPIC,
    CONF_WHITE_VALUE_COMMAND_TOPIC,
    CONF_WHITE_VALUE_STATE_TOPIC,
    DATA_AMPIO,
    DATA_AMPIO_DISPATCHERS,
    DEFAULT_QOS,
    SIGNAL_ADD_ENTITIES,
)
from .entity import AmpioEntity


class AmpioLight(AmpioEntity, LightEntity):
    """Representation of an Ampio light."""

    def __init__(self, config) -> None:
        """Initialize the light."""
        super().__init__(config)
        self._attr_is_on: bool | None = None
        self._attr_brightness: int | None = None
        self._attr_rgb_color: tuple[int, int, int] | None = None
        self._attr_rgbw_color: tuple[int, int, int, int] | None = None

        if config.get(CONF_RGB_COMMAND_TOPIC):
            if config.get(CONF_WHITE_VALUE_COMMAND_TOPIC):
                self._attr_supported_color_modes = {ColorMode.RGBW}
                self._attr_color_mode = ColorMode.RGBW
            else:
                self._attr_supported_color_modes = {ColorMode.RGB}
                self._attr_color_mode = ColorMode.RGB
        elif config.get(CONF_BRIGHTNESS_COMMAND_TOPIC):
            self._attr_supported_color_modes = {ColorMode.BRIGHTNESS}
            self._attr_color_mode = ColorMode.BRIGHTNESS
        else:
            self._attr_supported_color_modes = {ColorMode.ONOFF}
            self._attr_color_mode = ColorMode.ONOFF

    async def subscribe_topics(self) -> None:
        """Subscribe to light state topics."""
        topics = {}

        @callback
        def state_received(msg) -> None:
            try:
                self._attr_is_on = bool(int(msg.payload))
            except ValueError:
                self._attr_is_on = str(msg.payload).lower() == "on"
            self.async_write_ha_state()

        if state_topic := self._config.get(CONF_STATE_TOPIC):
            topics[CONF_STATE_TOPIC] = {
                "topic": state_topic,
                "msg_callback": state_received,
                "qos": DEFAULT_QOS,
            }

        @callback
        def brightness_received(msg) -> None:
            self._attr_brightness = max(0, min(255, round(float(msg.payload))))
            self._attr_is_on = self._attr_brightness > 0
            self.async_write_ha_state()

        if brightness_topic := self._config.get(CONF_BRIGHTNESS_STATE_TOPIC):
            topics[CONF_BRIGHTNESS_STATE_TOPIC] = {
                "topic": brightness_topic,
                "msg_callback": brightness_received,
                "qos": DEFAULT_QOS,
            }

        @callback
        def rgb_received(msg) -> None:
            try:
                values = tuple(int(value) for value in msg.payload.split(","))
            except ValueError:
                return
            if len(values) >= 4:
                self._attr_rgbw_color = values[:4]
            elif len(values) >= 3:
                self._attr_rgb_color = values[:3]
            self._attr_is_on = any(values)
            self.async_write_ha_state()

        if rgb_topic := self._config.get(CONF_RGB_STATE_TOPIC):
            topics[CONF_RGB_STATE_TOPIC] = {
                "topic": rgb_topic,
                "msg_callback": rgb_received,
                "qos": DEFAULT_QOS,
            }

        @callback
        def white_received(msg) -> None:
            white = max(0, min(255, round(float(msg.payload))))
            rgb = self._attr_rgb_color or (0, 0, 0)
            self._attr_rgbw_color = (*rgb, white)
            self._attr_is_on = self._attr_is_on or white > 0
            self.async_write_ha_state()

        if white_topic := self._config.get(CONF_WHITE_VALUE_STATE_TOPIC):
            topics[CONF_WHITE_VALUE_STATE_TOPIC] = {
                "topic": white_topic,
                "msg_callback": white_received,
                "qos": DEFAULT_QOS,
            }

        self._sub_state = await subscription.async_subscribe_topics(
            self.hass, self._sub_state, topics
        )

    async def async_will_remove_from_hass(self) -> None:
        """Unsubscribe when removed."""
        if self._sub_state is not None:
            self._sub_state = await subscription.async_unsubscribe_topics(
                self.hass, self._sub_state
            )

    async def async_turn_off(self, **kwargs) -> None:
        """Turn the light off."""
        if topic := self._config.get(CONF_RGB_COMMAND_TOPIC):
            async_publish(self.hass, topic, "off", 0, False)
        elif topic := self._config.get(CONF_COMMAND_TOPIC):
            async_publish(self.hass, topic, 0, 0, False)

    async def async_turn_on(self, **kwargs) -> None:
        """Turn the light on."""
        if rgbw := kwargs.get(ATTR_RGBW_COLOR):
            async_publish(
                self.hass,
                self._config[CONF_RGB_COMMAND_TOPIC],
                ",".join(map(str, rgbw)),
                0,
                False,
            )
            return

        if rgb := kwargs.get(ATTR_RGB_COLOR):
            async_publish(
                self.hass,
                self._config[CONF_RGB_COMMAND_TOPIC],
                ",".join(map(str, rgb)),
                0,
                False,
            )
            return

        brightness = kwargs.get(ATTR_BRIGHTNESS, self._attr_brightness or 255)
        if topic := self._config.get(CONF_BRIGHTNESS_COMMAND_TOPIC):
            async_publish(self.hass, topic, max(1, brightness), 0, False)
        elif topic := self._config.get(CONF_COMMAND_TOPIC):
            async_publish(self.hass, topic, 1, 0, False)
        elif topic := self._config.get(CONF_RGB_COMMAND_TOPIC):
            current = self._attr_rgbw_color or self._attr_rgb_color or (255, 255, 255)
            async_publish(
                self.hass, topic, ",".join(map(str, current)), 0, False
            )


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Ampio lights."""
    entities_to_create = hass.data[DATA_AMPIO][light.DOMAIN]
    unsub = async_dispatcher_connect(
        hass,
        SIGNAL_ADD_ENTITIES,
        functools.partial(
            discovery.async_add_entities,
            async_add_entities,
            entities_to_create,
            AmpioLight,
        ),
    )
    hass.data[DATA_AMPIO][DATA_AMPIO_DISPATCHERS].append(unsub)
