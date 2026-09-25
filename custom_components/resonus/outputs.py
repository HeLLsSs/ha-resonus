"""
Where the device can be told to play: itself, or one of the house's media
players, which is the choice the output sheet offers on the device and the
card offers here. The device does the playing either way (it holds the queue
and hands the speaker one track at a time); this is only the list, and the
name of the one that has the music now.
"""

from __future__ import annotations

from homeassistant.components.media_player import DOMAIN as MEDIA_PLAYER_DOMAIN
from homeassistant.components.media_player import MediaPlayerEntityFeature
from homeassistant.const import STATE_OFF, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN

# What the app sends as the output's id while it plays on the device itself
# (`currentOutput` in `store/player.ts` in the Resonus repository).
THIS_DEVICE = "phone"


def _worth(state: State) -> int:
    """
    How much a player is worth keeping when two entities are the same
    speaker: a queue first, then the ability to empty it, then seeking, then
    not being switched off. The reading the app makes in `playersFrom`
    (`lib/homeAssistant.ts`), so the card and the sheet pick the same one.
    """
    features = state.attributes.get("supported_features") or 0
    return (
        (16 if features & MediaPlayerEntityFeature.MEDIA_ENQUEUE else 0)
        + (8 if features & MediaPlayerEntityFeature.CLEAR_PLAYLIST else 0)
        + (4 if features & MediaPlayerEntityFeature.SEEK else 0)
        + (0 if state.state == STATE_OFF else 1)
    )


def outputs(hass: HomeAssistant, title: str) -> dict[str, str]:
    """
    Name to id: the device itself first, under the name it was set up with,
    then every media player a URL can be handed to, one row per name. One
    speaker is often several entities under the same name, and the one kept
    is the one that plays best. This integration's own players are left out:
    a phone cannot play through another phone.
    """
    registry = er.async_get(hass)
    best: dict[str, State] = {}
    for state in hass.states.async_all(MEDIA_PLAYER_DOMAIN):
        if state.state == STATE_UNAVAILABLE:
            continue
        features = state.attributes.get("supported_features") or 0
        if not features & MediaPlayerEntityFeature.PLAY_MEDIA:
            continue
        entry = registry.async_get(state.entity_id)
        if entry is not None and entry.platform == DOMAIN:
            continue
        held = best.get(state.name)
        if held is None or _worth(state) > _worth(held):
            best[state.name] = state
    players = {name: state.entity_id for name, state in sorted(best.items(), key=lambda row: row[0].casefold())}
    return {title: THIS_DEVICE, **{name: entity_id for name, entity_id in players.items() if name != title}}


def current_output(hass: HomeAssistant, title: str, output_id: str, output_name: str) -> str:
    """
    The name of what has the music, as the list above would name it: the
    device's own name for itself, a player's current name for one of the
    house's, and whatever the app called it for an output only the device
    can see (a Chromecast, a renderer, a LinkPlay speaker on its own API).
    """
    if output_id == THIS_DEVICE:
        return title
    if output_id.startswith(f"{MEDIA_PLAYER_DOMAIN}."):
        state = hass.states.get(output_id)
        return state.name if state else output_name or output_id
    return output_name or output_id
