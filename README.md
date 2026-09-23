# Home Assistant Ampio Custom Integration

[![GH-release](https://img.shields.io/github/v/release/kstaniek/ampio-hacc.svg?style=flat-square)](https://github.com/kstaniek/ampio-hacc/releases)
[![GH-downloads](https://img.shields.io/github/downloads/kstaniek/ampio-hacc/total?style=flat-square)](https://github.com/kstaniek/ampio-hacc/releases)
[![GH-last-commit](https://img.shields.io/github/last-commit/kstaniek/ampio-hacc.svg?style=flat-square)](https://github.com/kstaniek/ampio-hacc/commits/master)
[![GH-code-size](https://img.shields.io/github/languages/code-size/kstaniek/ampio-hacc.svg?color=red&style=flat-square)](https://github.com/kstaniek/ampio-hacc)
[![hacs_badge](https://img.shields.io/badge/HACS-Default-orange.svg?style=flat-square)](https://github.com/hacs)


[![Ampio](https://ampio.pl/wp-content/themes/1140FluidStarkers/images/ampio_dark.png)](https://ampio.pl)

This is a custom integration of the Ampio Smart Home System with Home Assistant.

It connects directly to the MQTT broker running on the Ampio Server. The broker
address and credentials are configured in the integration; Home Assistant's
built-in MQTT integration is not required.

## Requirements

- Home Assistant Core 2026.9.0 or newer
- Ampio MQTT Bridge 3.41.2 or newer
- Ampio v1 MQTT topics (`ampio/from/...` and `ampio/to/...`)

Currently there are following modules supported:
- MSERV-3s - flags
- MCON - Satel only
- MSENS - Both types
- MROL-4s
- MPR-8s
- MOC-4
- MRT-16s
- MLED-1
- MDIM-8s
- MRGBu-1
- MDOT-2
- MDOT-4
- MDOT-9
- MDOT-15LCD

## Installation

Install the repository through HACS as a custom integration, then restart Home
Assistant. For manual installation, copy `custom_components/ampio` to
`/config/custom_components/ampio` and restart Home Assistant.

## Configuration

Go to **Settings → Devices & services → Add integration**, select **Ampio**,
and enter the Ampio MQTT broker host, port, username, and password.

![config](https://github.com/kstaniek/ampio-hacc/blob/master/static/config1.png)

Provide the Ampio server address and leave port `1883` unless your broker uses a
different port. Use the MQTT credentials configured on the Ampio Server.

![config](https://github.com/kstaniek/ampio-hacc/blob/master/static/config2.png)

After setup, the integration requests the CAN device list and descriptions over
MQTT and creates the supported devices and entities automatically.

![config](https://github.com/kstaniek/ampio-hacc/blob/master/static/config3.png)

The configuration is done.

## Thanks to

Olek from Ampio for help, patience and effort to build the stable MQTT Broker for Ampio Smart Home System.
