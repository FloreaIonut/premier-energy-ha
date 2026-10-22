"""Integrarea Premier Energy (facturi gaze, portal my.premierenergy.ro)."""

from __future__ import annotations

from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import PremierEnergyApi
from .coordinator import PremierEnergyConfigEntry, PremierEnergyCoordinator

PLATFORMS = [Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: PremierEnergyConfigEntry) -> bool:
    """Pornește integrarea."""
    api = PremierEnergyApi(
        async_get_clientsession(hass), entry.data[CONF_EMAIL], entry.data[CONF_PASSWORD]
    )
    coordinator = PremierEnergyCoordinator(hass, entry, api)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: PremierEnergyConfigEntry) -> bool:
    """Oprește integrarea."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
