"""Module and entity discovery."""
import json
import logging
import re
from collections.abc import Callable
from typing import Any

import homeassistant.helpers.device_registry as dr
import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send

from . import client as ampio
from . import subscription
from .const import (
    ATTR_VERSION,
    DATA_AMPIO,
    DATA_AMPIO_API,
    DATA_AMPIO_MODULES,
    DATA_AMPIO_UNIQUE_IDS,
    DEFAULT_QOS,
    DOMAIN,
    SIGNAL_ADD_ENTITIES,
)
from .models import AmpioModuleInfo, ItemName

REQUEST_AMPIO_VERSION = "ampio/to/info/version"
RESPONSE_AMPIO_VERSION = "ampio/from/info/version"

REQUEST_MODULE_DISCOVERY = "ampio/to/can/dev/list"
RESPONSE_MODULE_DISCOVERY = "ampio/from/can/dev/list"

REQUEST_MODULE_NAMES = "ampio/to/{mac}/description"
RESPONSE_MODULE_NAMES = "ampio/from/+/description"

DISCOVERY_UNSUBSCRIBE = "ampio_discovery_unsubscribe"

# ampio/from/1B88/description
MAC_FROM_TOPIC_RE = re.compile(r"^ampio/from/(?P<mac>.*)/.*$")

_LOGGER = logging.getLogger(__name__)


async def async_start(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Start Ampio discovery."""
    topics = {}

    @callback
    def version_info_received(msg):
        """Process the version info message."""
        _LOGGER.debug("Version %s", msg.payload)
        try:
            data = json.loads(msg.payload)
        except json.JSONDecodeError:
            _LOGGER.error("Unable to decode Ampio MQTT Server version")
            return
        version = data.get(ATTR_VERSION, "N/A")
        device_registry = dr.async_get(hass)
        device_registry.async_get_or_create(
            config_entry_id=config_entry.entry_id,
            identifiers={(DOMAIN, str("ampio-mqtt"))},
            name="Ampio MQTT Server",
            manufacturer="Ampio",
            model="MQTT Server",
            sw_version=version,
        )

    topics[RESPONSE_AMPIO_VERSION] = {
        "topic": RESPONSE_AMPIO_VERSION,
        "msg_callback": version_info_received,
        "qos": DEFAULT_QOS,
    }

    @callback
    def device_list_received(msg):
        """Process device list info message."""
        try:
            payload = json.loads(msg.payload)
        except ValueError as err:
            _LOGGER.error("Unable to parse JSON module list: %s", err)
            return

        _LOGGER.debug("Module list payload: %s", payload)
        try:
            modules = AmpioModuleInfo.from_topic_payload(payload)
        except vol.Invalid as err:
            _LOGGER.error(
                "Unexpected Ampio module list payload %s: %s", payload, err
            )
            return

        for module in modules:
            data_modules = hass.data[DATA_AMPIO_MODULES]
            async_setup_device_registry(hass, config_entry, module)
            data_modules[module.user_mac] = module
            ampio.async_publish(
                hass, REQUEST_MODULE_NAMES.format(mac=module.user_mac), "1", 0, False
            )
        if not modules:
            _LOGGER.info("No Ampio modules discovered")
            async_load_entities(hass)

    topics[RESPONSE_MODULE_DISCOVERY] = {
        "topic": RESPONSE_MODULE_DISCOVERY,
        "msg_callback": device_list_received,
        "qos": DEFAULT_QOS,
    }

    @callback
    def module_names_received(msg):
        """Handle module names update."""
        matched = MAC_FROM_TOPIC_RE.match(msg.topic)
        if matched:
            mac = matched.group("mac").upper()
            module = hass.data[DATA_AMPIO_MODULES].get(mac)
            if module is None:
                return
        else:
            return

        try:
            payload = json.loads(msg.payload)
        except ValueError as err:
            _LOGGER.error("Unable to parse JSON module names: %s", err)
            return

        try:
            module.names = ItemName.from_topic_payload(payload)
        except vol.Invalid as err:
            _LOGGER.error(
                "Unexpected Ampio names payload for %s: %s", mac, err
            )
            return
        module.update_configs()

        _LOGGER.info(
            "Discovered: %s-%s (%s): %s",
            module.code,
            module.model,
            module.software,
            module.name,
        )
        for component, configs in module.configs.items():
            for config in configs:
                unique_id = config.get("unique_id")
                if unique_id not in hass.data[DATA_AMPIO_UNIQUE_IDS]:
                    hass.data[DATA_AMPIO][component].append(config)
                    hass.data[DATA_AMPIO_UNIQUE_IDS].add(unique_id)
                else:
                    _LOGGER.debug("Ignoring: %s", unique_id)

        del hass.data[DATA_AMPIO_MODULES][mac]
        async_load_entities(hass)
        if len(hass.data[DATA_AMPIO_MODULES]) == 0:  # ALL MODULES discovered
            _LOGGER.info("All modules discovered")

    topics[RESPONSE_MODULE_NAMES] = {
        "topic": RESPONSE_MODULE_NAMES,
        "msg_callback": module_names_received,
        "qos": DEFAULT_QOS,
    }

    hass.data[DATA_AMPIO_MODULES] = {}
    hass.data[DATA_AMPIO_UNIQUE_IDS] = set()

    hass.data[DISCOVERY_UNSUBSCRIBE] = await subscription.async_subscribe_topics(
        hass, hass.data.get(DISCOVERY_UNSUBSCRIBE), topics
    )

    return True


async def async_request_discovery(hass: HomeAssistant) -> None:
    """Request broker and CAN module information."""
    client = hass.data[DATA_AMPIO][DATA_AMPIO_API]
    await client.async_publish(REQUEST_AMPIO_VERSION, "", 0, False)
    await client.async_publish(REQUEST_MODULE_DISCOVERY, "1", 0, False)


@callback
async def async_stop(hass: HomeAssistant) -> None:
    """Stop Ampio MQTT Discovery."""
    if sub_state := hass.data.pop(DISCOVERY_UNSUBSCRIBE, None):
        await subscription.async_unsubscribe_topics(hass, sub_state)


@callback
def async_setup_device_registry(
    hass: HomeAssistant, entry: ConfigEntry, device_info: AmpioModuleInfo
):
    """Set up device registry feature for a particular config entry."""
    device_registry = dr.async_get(hass)
    return device_registry.async_get_or_create(
        config_entry_id=entry.entry_id, **device_info.as_hass_device()
    )


@callback
def async_add_entities(
    _async_add_entities: Callable, entities: list[dict[str, Any]], klass
) -> None:
    """Add entities helper."""
    if not entities:
        return

    to_add = [klass(config) for config in entities]
    _async_add_entities(to_add, update_before_add=True)
    entities.clear()


@callback
def async_load_entities(hass: HomeAssistant) -> None:
    """Load entities after integration was setup."""
    async_dispatcher_send(hass, SIGNAL_ADD_ENTITIES)
