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


def _facturi(d: dict) -> list[dict]:
    return d.get("facturi") or []


@dataclass(frozen=True, kw_only=True)
class PremierSensorDescription(SensorEntityDescription):
    """Descriere senzor + funcția de valoare (primește dict-ul PoD: facturi/indexi/consum)."""

    value_fn: Callable[[dict[str, Any]], Any]
    attr_key: str | None = None


DESCRIPTIONS: tuple[PremierSensorDescription, ...] = (
    PremierSensorDescription(
        key="ultima_factura_suma",
        translation_key="ultima_factura_suma",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement="RON",
        suggested_display_precision=2,
        value_fn=lambda d: _facturi(d)[0]["suma"] if _facturi(d) else None,
        attr_key="facturi",
    ),
    PremierSensorDescription(
        key="scadenta",
        translation_key="scadenta",
        device_class=SensorDeviceClass.DATE,
        value_fn=lambda d: _to_date(_facturi(d)[0]["scadenta"]) if _facturi(d) else None,
    ),
    PremierSensorDescription(
        key="data_emiterii",
        translation_key="data_emiterii",
        device_class=SensorDeviceClass.DATE,
        value_fn=lambda d: _to_date(_facturi(d)[0]["emisa"]) if _facturi(d) else None,
    ),
    PremierSensorDescription(
        key="numar_factura",
        translation_key="numar_factura",
        value_fn=lambda d: _facturi(d)[0]["numar"] if _facturi(d) else None,
    ),
    PremierSensorDescription(
        key="numar_facturi",
        translation_key="numar_facturi",
        value_fn=lambda d: len(_facturi(d)),
    ),
    PremierSensorDescription(
        key="sold_de_plata",
        translation_key="sold_de_plata",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement="RON",
        suggested_display_precision=2,
        value_fn=lambda d: round(
            sum(i["rest"] for i in _facturi(d) if isinstance(i.get("rest"), (int, float))), 2
        ),
    ),
    PremierSensorDescription(
        key="facturi_neplatite",
        translation_key="facturi_neplatite",
        value_fn=lambda d: sum(
            1 for i in _facturi(d) if isinstance(i.get("rest"), (int, float)) and i["rest"] > 0
        ),
    ),
    PremierSensorDescription(
        key="index_curent",
        translation_key="index_curent",
        icon="mdi:counter",
        value_fn=lambda d: (d.get("indexi") or [{}])[0].get("index") if d.get("indexi") else None,
        attr_key="indexi",
    ),
    PremierSensorDescription(
        key="consum_ultima_luna",
        translation_key="consum_ultima_luna",
        native_unit_of_measurement="kWh",
        suggested_display_precision=0,
        icon="mdi:fire",
        value_fn=lambda d: (d.get("consum") or [{}])[0].get("kwh") if d.get("consum") else None,
        attr_key="consum",
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
            configuration_url="https://app.premierenergy.ro",
        )

    @property
    def _data(self) -> dict[str, Any]:
        return self.coordinator.data.get(self._pod) or {}

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self._data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        key = self.entity_description.attr_key
        if not key:
            return None
        data = self._data
        attrs: dict[str, Any] = {"pod": self._pod}
        if key == "facturi":
            attrs["adresa"] = data.get("adresa")
        attrs[key] = (data.get(key) or [])[:MAX_INVOICES_ATTR]
        return attrs
