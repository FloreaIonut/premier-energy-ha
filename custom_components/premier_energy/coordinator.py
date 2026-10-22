"""Coordonator de date (interogare la 6 ore)."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    PremierEnergyApi,
    PremierEnergyAuthError,
    PremierEnergyConnectionError,
)
from .const import DOMAIN, SCAN_INTERVAL

_LOGGER = logging.getLogger(__name__)

type PremierEnergyConfigEntry = ConfigEntry[PremierEnergyCoordinator]


class PremierEnergyCoordinator(DataUpdateCoordinator[dict[str, dict[str, Any]]]):
    """Aduce facturile pentru toate PoD-urile de gaz."""

    config_entry: PremierEnergyConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: PremierEnergyConfigEntry, api: PremierEnergyApi
    ) -> None:
        super().__init__(
            hass, _LOGGER, config_entry=entry, name=DOMAIN, update_interval=SCAN_INTERVAL
        )
        self.api = api

    async def _async_update_data(self) -> dict[str, dict[str, Any]]:
        try:
            return await self.api.async_get_data()
        except PremierEnergyAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except PremierEnergyConnectionError as err:
            raise UpdateFailed(str(err)) from err
