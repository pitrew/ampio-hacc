"""Data validators."""
from typing import Any, List, TypeVar, Union

import voluptuous as vol

ATTR_MAC = "mac"
ATTR_USERMAC = "user_mac"
ATTR_TYPE = "typ"
ATTR_PCB = "pcb"
ATTR_SOFTWARE = "soft_ver"
ATTR_PROTOCOL = "protocol"
ATTR_I = "i"
ATTR_O = "o"
ATTR_A = "a"
ATTR_AU = "au"
ATTR_FLAG = "f"
ATTR_NAME = "name"
ATTR_DEVICES = "devices"
ATTR_DEVICE = "device"
ATTR_DATE_PROD = "date_prod"
ATTR_T = "t"
ATTR_N = "n"
ATTR_D = "d"
ATTR_S = "s"

T = TypeVar("T")


def string(value: Any) -> str:
    """Coerce value to string, except for None."""
    if value is None:
        raise vol.Invalid("string value is None")
    if isinstance(value, (list, dict)):
        raise vol.Invalid("value should be a string")

    return str(value)


def ensure_list(value: Union[T, List[T], None]) -> List[T]:
    """Wrap value in list if it is not one."""
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def lenient_int(value: Any) -> int:
    """Coerce a value to int, falling back to 0.

    Firmware revisions report some of these fields as strings, floats or
    formatted dates, and none of them are worth failing discovery over.
    """
    try:
        return int(value)
    except (TypeError, ValueError):
        pass
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


AMPIO_DEVICE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_MAC): string,
        vol.Required(ATTR_USERMAC): string,
        vol.Required(ATTR_TYPE): lenient_int,
        vol.Optional(ATTR_PCB, default=0): lenient_int,
        vol.Optional(ATTR_SOFTWARE, default=0): lenient_int,
        vol.Optional(ATTR_PROTOCOL, default=0): lenient_int,
        vol.Optional(ATTR_DATE_PROD, default=0): lenient_int,
        vol.Optional(ATTR_I, default=0): lenient_int,
        vol.Optional(ATTR_O, default=0): lenient_int,
        vol.Optional(ATTR_A, default=0): lenient_int,
        vol.Optional(ATTR_AU, default=0): lenient_int,
        vol.Optional(ATTR_T, default=0): lenient_int,
        vol.Optional(ATTR_FLAG, default=0): lenient_int,
        vol.Optional(ATTR_NAME, default=""): string,
    },
    extra=vol.ALLOW_EXTRA,
)

# Devices are validated one by one so a single unexpected entry cannot
# discard the whole CAN device list.
AMPIO_DEVICES_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_S, default=0): lenient_int,
        vol.Optional(ATTR_D, default=[]): vol.All(ensure_list, [dict]),
    },
    extra=vol.ALLOW_EXTRA,
)

AMPIO_DESCRIPTION_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_T): string,
        vol.Required(ATTR_N): lenient_int,
        vol.Required(ATTR_D): string,
    },
    extra=vol.ALLOW_EXTRA,
)

AMPIO_DESCRIPTIONS_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_S, default=0): lenient_int,
        vol.Optional(ATTR_D, default=[]): vol.All(ensure_list, [dict]),
    },
    extra=vol.ALLOW_EXTRA,
)
