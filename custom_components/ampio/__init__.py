"""The Ampio integration."""
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError

from .client import AmpioAPI
from .const import DATA_AMPIO, DATA_AMPIO_API, DATA_AMPIO_DISPATCHERS, PLATFORMS
from .discovery import async_request_discovery
from .discovery import async_start as async_start_discovery
from .discovery import async_stop as async_stop_discovery

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Ampio from a config entry."""
    runtime = {platform.value: [] for platform in PLATFORMS}
    hass.data[DATA_AMPIO] = runtime
    runtime[DATA_AMPIO_DISPATCHERS] = []

    client = AmpioAPI(hass, entry, dict(entry.data))
    runtime[DATA_AMPIO_API] = client

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await async_start_discovery(hass, entry)
    try:
        await client.async_connect()
        await async_request_discovery(hass)
    except (OSError, HomeAssistantError) as err:
        await client.async_disconnect()
        await async_stop_discovery(hass)
        await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
        hass.data.pop(DATA_AMPIO, None)
        raise ConfigEntryNotReady(
            f"Unable to connect to Ampio MQTT broker: {err}"
        ) from err

    entry.async_on_unload(entry.add_update_listener(_async_entry_updated))
    return True


async def _async_entry_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload Ampio when connection settings change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload an Ampio config entry."""
    runtime = hass.data.get(DATA_AMPIO, {})
    await async_stop_discovery(hass)

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if not unload_ok:
        return False

    for unsub_dispatcher in runtime.get(DATA_AMPIO_DISPATCHERS, []):
        unsub_dispatcher()
    if client := runtime.get(DATA_AMPIO_API):
        await client.async_disconnect()
    hass.data.pop(DATA_AMPIO, None)
    return True
