"""
The output as a `select` entity: the same choice as the media player's
source, on a row a dashboard can hold on its own. The source is only
reachable through the player's dialog, which on a wall tablet is a tap too
many between a track and the speaker it should come out of.
"""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import ResonusConfigEntry, ResonusData
from .const import DOMAIN
from .outputs import current_output, outputs


async def async_setup_entry(
    hass: HomeAssistant, entry: ResonusConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([ResonusOutputSelect(entry)])


class ResonusOutputSelect(SelectEntity):
    """Where one device running Resonus plays."""

    _attr_has_entity_name = True
    _attr_translation_key = "output"
    _attr_icon = "mdi:speaker-multiple"

    def __init__(self, entry: ResonusConfigEntry) -> None:
        self._entry = entry
        self._data: ResonusData = entry.runtime_data
        self._attr_unique_id = f"{entry.entry_id}_output"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry.entry_id)})

    async def async_added_to_hass(self) -> None:
        @callback
        def updated() -> None:
            self.async_write_ha_state()

        self._data.listeners.append(updated)
        self.async_on_remove(lambda: self._data.listeners.remove(updated))

    @property
    def options(self) -> list[str]:
        return list(outputs(self.hass, self._entry.title))

    @property
    def current_option(self) -> str:
        state = self._data.state
        return current_output(self.hass, self._entry.title, state.output_id, state.output_name)

    async def async_select_option(self, option: str) -> None:
        output_id = outputs(self.hass, self._entry.title).get(option)
        if output_id is None:
            raise HomeAssistantError(f"{self._entry.title} cannot play through {option}")
        await self._data.command(self.hass, "output", id=output_id)
