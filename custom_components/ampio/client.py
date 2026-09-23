"""Ampio MQTT client."""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import paho.mqtt.client as mqtt
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_CLIENT_ID, CONF_PASSWORD, CONF_PORT, CONF_USERNAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.util import dt as dt_util

from .const import (
    AMPIO_CONNECTED,
    AMPIO_DISCONNECTED,
    CONF_BROKER,
    DATA_AMPIO,
    DATA_AMPIO_API,
    DEFAULT_QOS,
)
from .models import Message, PublishPayloadType

_LOGGER = logging.getLogger(__name__)

CONF_KEEPALIVE = "keepalive"
DEFAULT_KEEPALIVE = 60
CONNECT_TIMEOUT = 10


@dataclass(slots=True)
class Subscription:
    """An Ampio MQTT subscription."""

    topic: str
    job: Callable[[Message], Any]
    qos: int
    encoding: str | None


@callback
def async_publish(
    hass: HomeAssistant,
    topic: str,
    payload: PublishPayloadType,
    qos: int | None = None,
    retain: bool | None = None,
) -> None:
    """Schedule publishing a message to the Ampio broker."""
    client: AmpioAPI = hass.data[DATA_AMPIO][DATA_AMPIO_API]
    hass.async_create_task(
        client.async_publish(
            topic,
            payload,
            DEFAULT_QOS if qos is None else qos,
            False if retain is None else retain,
        ),
        f"Publish Ampio MQTT message to {topic}",
    )


async def async_subscribe(
    hass: HomeAssistant,
    topic: str,
    msg_callback: Callable[[Message], Any],
    qos: int = DEFAULT_QOS,
    encoding: str | None = "utf-8",
) -> Callable[[], None]:
    """Subscribe to an Ampio MQTT topic."""
    client: AmpioAPI = hass.data[DATA_AMPIO][DATA_AMPIO_API]
    return await client.async_subscribe(topic, msg_callback, qos, encoding)


class AmpioAPI:
    """Manage the connection to the Ampio MQTT broker."""

    def __init__(
        self, hass: HomeAssistant, config_entry: ConfigEntry, conf: dict[str, Any]
    ) -> None:
        """Initialize the client."""
        self.hass = hass
        self.config_entry = config_entry
        self.conf = conf
        self.subscriptions: list[Subscription] = []
        self.connected = False
        self._connect_result: asyncio.Future[None] | None = None
        self._paho_lock = asyncio.Lock()

        client_id = conf.get(CONF_CLIENT_ID, "")
        self._mqttc = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=client_id,
            protocol=mqtt.MQTTv311,
        )
        if username := conf.get(CONF_USERNAME):
            self._mqttc.username_pw_set(username, conf.get(CONF_PASSWORD))
        self._mqttc.on_connect = self._mqtt_on_connect
        self._mqttc.on_disconnect = self._mqtt_on_disconnect
        self._mqttc.on_message = self._mqtt_on_message

    async def async_connect(self) -> None:
        """Connect and wait for the broker to accept the connection."""
        self._connect_result = self.hass.loop.create_future()
        try:
            await self.hass.async_add_executor_job(
                self._mqttc.connect,
                self.conf[CONF_BROKER],
                self.conf.get(CONF_PORT, 1883),
                self.conf.get(CONF_KEEPALIVE, DEFAULT_KEEPALIVE),
            )
            self._mqttc.loop_start()
            async with asyncio.timeout(CONNECT_TIMEOUT):
                await self._connect_result
        except TimeoutError as err:
            await self.async_disconnect()
            raise OSError("Timed out connecting to the MQTT broker") from err

    async def async_disconnect(self) -> None:
        """Disconnect the MQTT client and stop its network thread."""
        if self.connected:
            await self.hass.async_add_executor_job(self._mqttc.disconnect)
        await self.hass.async_add_executor_job(self._mqttc.loop_stop)
        self.connected = False

    async def async_publish(
        self, topic: str, payload: PublishPayloadType, qos: int, retain: bool
    ) -> None:
        """Publish a message."""
        async with self._paho_lock:
            info = await self.hass.async_add_executor_job(
                self._mqttc.publish, topic, payload, qos, retain
            )
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            raise HomeAssistantError(
                f"Error publishing to Ampio MQTT: {mqtt.error_string(info.rc)}"
            )

    async def async_subscribe(
        self,
        topic: str,
        msg_callback: Callable[[Message], Any],
        qos: int,
        encoding: str | None,
    ) -> Callable[[], None]:
        """Register a subscription."""
        if not isinstance(topic, str):
            raise HomeAssistantError("MQTT topic must be a string")

        subscription = Subscription(topic, msg_callback, qos, encoding)
        self.subscriptions.append(subscription)
        if self.connected:
            await self._async_perform_subscription(topic, qos)

        @callback
        def async_remove() -> None:
            if subscription not in self.subscriptions:
                return
            self.subscriptions.remove(subscription)
            if self.connected and not any(
                other.topic == topic for other in self.subscriptions
            ):
                self.hass.async_create_task(
                    self._async_unsubscribe(topic),
                    f"Unsubscribe from Ampio MQTT topic {topic}",
                )

        return async_remove

    async def _async_perform_subscription(self, topic: str, qos: int) -> None:
        """Subscribe through paho."""
        async with self._paho_lock:
            result, _mid = await self.hass.async_add_executor_job(
                self._mqttc.subscribe, topic, qos
            )
        self._raise_on_error(result)

    async def _async_unsubscribe(self, topic: str) -> None:
        """Unsubscribe through paho."""
        async with self._paho_lock:
            result, _mid = await self.hass.async_add_executor_job(
                self._mqttc.unsubscribe, topic
            )
        self._raise_on_error(result)

    def _mqtt_on_connect(
        self,
        _client: mqtt.Client,
        _userdata: Any,
        _flags: mqtt.ConnectFlags,
        reason_code: mqtt.ReasonCode,
        _properties: mqtt.Properties | None,
    ) -> None:
        """Pass a paho connection callback to the HA event loop."""
        self.hass.loop.call_soon_threadsafe(self._async_handle_connect, reason_code)

    @callback
    def _async_handle_connect(self, reason_code: mqtt.ReasonCode) -> None:
        """Handle connection on the HA event loop."""
        if reason_code.is_failure:
            error = OSError(f"MQTT broker rejected connection: {reason_code}")
            if self._connect_result and not self._connect_result.done():
                self._connect_result.set_exception(error)
            return

        self.connected = True
        self.hass.async_create_task(
            self._async_finish_connect(), "Finish Ampio MQTT connection"
        )

    async def _async_finish_connect(self) -> None:
        """Restore subscriptions before reporting a successful connection."""
        topics: dict[str, int] = {}
        for subscription in self.subscriptions:
            topics[subscription.topic] = max(
                subscription.qos, topics.get(subscription.topic, 0)
            )
        try:
            for topic, qos in topics.items():
                await self._async_perform_subscription(topic, qos)
        except Exception as err:  # noqa: BLE001
            if self._connect_result and not self._connect_result.done():
                self._connect_result.set_exception(err)
            return

        if self._connect_result and not self._connect_result.done():
            self._connect_result.set_result(None)
        async_dispatcher_send(self.hass, AMPIO_CONNECTED)
        _LOGGER.info(
            "Connected to Ampio MQTT broker %s:%s",
            self.conf[CONF_BROKER],
            self.conf.get(CONF_PORT, 1883),
        )

    def _mqtt_on_message(
        self, _client: mqtt.Client, _userdata: Any, msg: mqtt.MQTTMessage
    ) -> None:
        """Pass a paho message callback to the HA event loop."""
        self.hass.loop.call_soon_threadsafe(self._async_handle_message, msg)

    @callback
    def _async_handle_message(self, msg: mqtt.MQTTMessage) -> None:
        """Dispatch a message on the HA event loop."""
        for subscription in tuple(self.subscriptions):
            if not mqtt.topic_matches_sub(subscription.topic, msg.topic):
                continue

            payload: str | bytes = msg.payload
            if subscription.encoding is not None:
                try:
                    payload = msg.payload.decode(subscription.encoding)
                except UnicodeDecodeError:
                    _LOGGER.warning("Unable to decode MQTT payload on %s", msg.topic)
                    continue

            message = Message(
                msg.topic,
                payload,
                msg.qos,
                msg.retain,
                subscription.topic,
                dt_util.utcnow(),
            )
            try:
                result = subscription.job(message)
                if inspect.isawaitable(result):
                    self.hass.async_create_task(
                        result, f"Handle Ampio MQTT message on {msg.topic}"
                    )
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Error handling Ampio MQTT message on %s", msg.topic)

    def _mqtt_on_disconnect(
        self,
        _client: mqtt.Client,
        _userdata: Any,
        _disconnect_flags: mqtt.DisconnectFlags,
        reason_code: mqtt.ReasonCode,
        _properties: mqtt.Properties | None,
    ) -> None:
        """Pass a paho disconnect callback to the HA event loop."""
        self.hass.loop.call_soon_threadsafe(
            self._async_handle_disconnect, reason_code
        )

    @callback
    def _async_handle_disconnect(self, reason_code: mqtt.ReasonCode) -> None:
        """Handle disconnect on the HA event loop."""
        self.connected = False
        async_dispatcher_send(self.hass, AMPIO_DISCONNECTED)
        if reason_code.is_failure:
            _LOGGER.warning("Disconnected from Ampio MQTT broker: %s", reason_code)

    @staticmethod
    def _raise_on_error(result_code: mqtt.MQTTErrorCode) -> None:
        if result_code != mqtt.MQTT_ERR_SUCCESS:
            raise HomeAssistantError(
                f"Error talking to Ampio MQTT: {mqtt.error_string(result_code)}"
            )
