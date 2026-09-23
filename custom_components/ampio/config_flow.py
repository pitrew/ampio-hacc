"""Config flow for the Ampio integration."""

from __future__ import annotations

from queue import Empty, Queue
from typing import Any

import paho.mqtt.client as mqtt
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.const import CONF_PASSWORD, CONF_PORT, CONF_USERNAME
from homeassistant.helpers import config_validation as cv
from zeroconf.asyncio import AsyncServiceInfo

from .const import CONF_BROKER, DOMAIN

DEFAULT_PORT = 1883
CONNECT_TIMEOUT = 10


def _try_connection(user_input: dict[str, Any]) -> bool:
    """Test broker settings outside the event loop."""
    result: Queue[bool] = Queue(maxsize=1)
    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        protocol=mqtt.MQTTv311,
    )
    if username := user_input.get(CONF_USERNAME):
        client.username_pw_set(username, user_input.get(CONF_PASSWORD))

    def on_connect(
        _client: mqtt.Client,
        _userdata: Any,
        _flags: mqtt.ConnectFlags,
        reason_code: mqtt.ReasonCode,
        _properties: mqtt.Properties | None,
    ) -> None:
        result.put(not reason_code.is_failure)

    client.on_connect = on_connect
    try:
        client.connect_async(user_input[CONF_BROKER], user_input[CONF_PORT])
        client.loop_start()
        return result.get(timeout=CONNECT_TIMEOUT)
    except (OSError, Empty):
        return False
    finally:
        client.disconnect()
        client.loop_stop()


class AmpioFlowHandler(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle an Ampio config flow."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the flow."""
        self._broker: str | None = None
        self._port: int | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Start a user initiated flow."""
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")
        return await self.async_step_broker(user_input)

    async def async_step_broker(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Collect and validate Ampio MQTT settings."""
        errors: dict[str, str] = {}
        if user_input is not None:
            can_connect = await self.hass.async_add_executor_job(
                _try_connection, user_input
            )
            if can_connect:
                return self.async_create_entry(
                    title=user_input[CONF_BROKER], data=user_input
                )
            errors["base"] = "cannot_connect"

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_BROKER, default=self._broker or vol.UNDEFINED
                ): cv.string,
                vol.Required(
                    CONF_PORT, default=self._port or DEFAULT_PORT
                ): cv.port,
                vol.Optional(CONF_USERNAME): cv.string,
                vol.Optional(CONF_PASSWORD): cv.string,
            }
        )
        return self.async_show_form(
            step_id="broker", data_schema=schema, errors=errors
        )

    async def async_step_zeroconf(
        self, discovery_info: AsyncServiceInfo
    ) -> ConfigFlowResult:
        """Prepare a flow for a discovered Ampio broker."""
        addresses = discovery_info.parsed_addresses()
        host = addresses[0] if addresses else discovery_info.server.rstrip(".")
        await self.async_set_unique_id(host)
        self._abort_if_unique_id_configured()
        self._broker = host
        self._port = discovery_info.port
        return await self.async_step_broker()
