"""
Resonus: the phone as a media player Home Assistant can browse and play from.

Two halves, both local:

- **Out**, a command: Home Assistant asks the Companion app on the phone to
  broadcast an intent, which the app answers whether it is open or not (see
  `docs/INTENTS.md` in the Resonus repository). Nothing is polled and nothing
  is held open; the phone is told, and that is all.
- **In**, the state: the app pushes what it is playing to a webhook this
  integration registers, on every change worth a repaint. The webhook id is
  the one the app shows under Settings › Home Assistant.

The library itself is read from the Subsonic server rather than from the
phone, so the browser answers with the screen off.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from aiohttp.web import Request, Response
from homeassistant.components import webhook
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED, Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import dt as dt_util

from .const import ACTION_COMMAND, CONF_NOTIFY_SERVICE, CONF_WEBHOOK_ID, DOMAIN, PACKAGE
from .subsonic import Credentials, SubsonicClient

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.MEDIA_PLAYER, Platform.SELECT]


@dataclass
class ResonusState:
    """The last thing the phone said about itself."""

    playing: bool = False
    song_id: str = ""
    title: str = ""
    artist: str = ""
    album: str = ""
    album_id: str = ""
    cover_art: str = ""
    duration: int = 0
    position: int = 0
    volume: float = 1.0
    shuffle: bool = False
    repeat: str = "off"
    # Where it plays: `phone`, or one of the house's players by entity id, or
    # a word for an output only the device can see, with its name.
    output_id: str = "phone"
    output_name: str = ""
    updated_at: Any = field(default_factory=dt_util.utcnow)

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> ResonusState:
        """A push read defensively: it comes off the network, from a phone."""

        def text(key: str) -> str:
            value = payload.get(key)
            return value if isinstance(value, str) else ""

        def number(key: str) -> float:
            value = payload.get(key)
            return float(value) if isinstance(value, (int, float)) else 0.0

        repeat = text("repeat")
        return cls(
            playing=payload.get("playing") is True,
            song_id=text("songId"),
            title=text("title"),
            artist=text("artist"),
            album=text("album"),
            album_id=text("albumId"),
            cover_art=text("coverArt"),
            duration=int(number("duration")),
            position=int(number("position")),
            volume=min(1.0, max(0.0, number("volume"))),
            shuffle=payload.get("shuffle") is True,
            repeat=repeat if repeat in ("off", "all", "one") else "off",
            output_id=text("outputId") or "phone",
            output_name=text("outputName"),
        )


@dataclass
class ResonusData:
    """What the platform and the webhook share for one phone."""

    client: SubsonicClient
    notify_service: str
    state: ResonusState = field(default_factory=ResonusState)
    listeners: list[Any] = field(default_factory=list)

    @callback
    def updated(self, state: ResonusState) -> None:
        self.state = state
        for listener in self.listeners:
            listener()

    async def command(self, hass: HomeAssistant, command: str, **extras: str) -> None:
        """
        One intent, through the Companion app on the phone. The extras go as
        `key:value` pairs, which is the only shape `command_broadcast_intent`
        takes. Nothing waits for an answer: the app's own push comes back
        through the webhook a moment later.
        """
        pairs = ",".join(f"{key}:{value}" for key, value in {"command": command, **extras}.items())
        await hass.services.async_call(
            "notify",
            self.notify_service,
            {
                "message": "command_broadcast_intent",
                "data": {
                    "intent_package_name": PACKAGE,
                    "intent_action": ACTION_COMMAND,
                    "intent_extras": pairs,
                },
            },
            blocking=True,
        )


type ResonusConfigEntry = ConfigEntry[ResonusData]


async def async_setup_entry(hass: HomeAssistant, entry: ResonusConfigEntry) -> bool:
    """One phone: its library, its webhook and its entity."""
    credentials = Credentials(
        url=entry.data["url"].rstrip("/"),
        username=entry.data["username"],
        password=entry.data["password"],
    )
    entry.runtime_data = ResonusData(
        client=SubsonicClient(async_get_clientsession(hass), credentials),
        notify_service=entry.data[CONF_NOTIFY_SERVICE],
    )

    webhook_id = entry.data[CONF_WEBHOOK_ID]
    # From the network only: a push is a song title, but the address is
    # nobody's business past the front door, Nabu Casa included.
    webhook.async_register(hass, DOMAIN, entry.title, webhook_id, _handle_webhook, local_only=True)
    entry.async_on_unload(lambda: webhook.async_unregister(hass, webhook_id))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Home Assistant holds nothing across a restart and the push is one way,
    # so the phone is asked to say what it is playing; the card would
    # otherwise sit idle until the next track. A phone that is off or away
    # simply does not answer.
    if hass.is_running:
        entry.async_create_background_task(hass, _ask_for_state(hass, entry), f"{DOMAIN}_publish_state")
    else:
        # The Companion app's notify service is set up by another integration,
        # later in the same start: asked now, there would be nobody to ask.
        entry.async_on_unload(
            hass.bus.async_listen_once(
                EVENT_HOMEASSISTANT_STARTED,
                lambda _event: entry.async_create_background_task(
                    hass, _ask_for_state(hass, entry), f"{DOMAIN}_publish_state"
                ),
            )
        )
    return True


async def _ask_for_state(hass: HomeAssistant, entry: ResonusConfigEntry) -> None:
    try:
        await entry.runtime_data.command(hass, "publish_state")
    except Exception as err:  # noqa: BLE001 - a phone that is away is not an error
        _LOGGER.debug("Could not ask %s what it is playing: %s", entry.title, err)


async def async_unload_entry(hass: HomeAssistant, entry: ResonusConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _handle_webhook(hass: HomeAssistant, webhook_id: str, request: Request) -> Response:
    """
    A push from the app. The entry is found by the webhook id rather than
    held in a closure, so a reload leaves nothing stale behind.
    """
    try:
        payload = await request.json()
    except ValueError:
        return Response(status=400)
    if not isinstance(payload, dict):
        return Response(status=400)
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.data.get(CONF_WEBHOOK_ID) != webhook_id:
            continue
        data: ResonusData | None = getattr(entry, "runtime_data", None)
        if data is None:
            continue
        data.updated(ResonusState.from_payload(payload))
    return Response(status=200)
