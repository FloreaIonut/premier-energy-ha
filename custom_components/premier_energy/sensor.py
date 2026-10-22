"""Senzori pentru facturile de gaz Premier Energy."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MAX_INVOICES_ATTR
from .coordinator import PremierEnergyConfigEntry, PremierEnergyCoordinator


def _to_date(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


@dataclass(frozen=True, kw_only=True)
class PremierSensorDescription(SensorEntityDescription):
    """Descriere senzor + funcția de valoare (primește lista de facturi, nou -> vechi)."""

    value_fn: Callable[[list[dict[str, Any]]], Any]


DESCRIPTIONS: tuple[PremierSensorDescription, ...] = (
    PremierSensorDescription(
        key="ultima_factura_suma",
        translation_key="ultima_factura_suma",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement="RON",
        suggested_display_precision=2,
        value_fn=lambda f: f[0]["suma"] if f else None,
    ),
    PremierSensorDescription(
        key="scadenta",
        translation_key="scadenta",
        device_class=SensorDeviceClass.DATE,
        value_fn=lambda f: _to_date(f[0]["scadenta"]) if f else None,
    ),
    PremierSensorDescription(
        key="data_emiterii",
        translation_key="data_emiterii",
        device_class=SensorDeviceClass.DATE,
        value_fn=lambda f: _to_date(f[0]["emisa"]) if f else None,
    ),
    PremierSensorDescription(
        key="numar_factura",
        translation_key="numar_factura",
        value_fn=lambda f: f[0]["numar"] if f else None,
    ),
    PremierSensorDescription(
        key="numar_facturi",
        translation_key="numar_facturi",
        value_fn=lambda f: len(f),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PremierEnergyConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Creează senzorii pentru fiecare PoD de gaz."""
    coordinator = entry.runtime_data
    async_add_entities(
        PremierSensor(coordinator, pod, desc)
        for pod in coordinator.data
        for desc in DESCRIPTIONS
    )


class PremierSensor(CoordinatorEntity[PremierEnergyCoordinator], SensorEntity):
    """Senzor de factură pentru un PoD."""

    _attr_has_entity_name = True
    entity_description: PremierSensorDescription

    def __init__(
        self,
        coordinator: PremierEnergyCoordinator,
        pod: str,
        description: PremierSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._pod = pod
        self._attr_unique_id = f"{pod}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, pod)},
            name=f"Gaz {pod}",
            manufacturer="Premier Energy",
            model="Contract gaze",
            configuration_url="https://my.premierenergy.ro",
        )

    @property
    def _invoices(self) -> list[dict[str, Any]]:
        return (self.coordinator.data.get(self._pod) or {}).get("facturi", [])

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self._invoices)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.key != "ultima_factura_suma":
            return None
        data = self.coordinator.data.get(self._pod) or {}
        return {
            "pod": self._pod,
            "adresa": data.get("adresa"),
            "facturi": self._invoices[:MAX_INVOICES_ATTR],
        }
