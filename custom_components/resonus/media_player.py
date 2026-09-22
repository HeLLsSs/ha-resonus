"""
The entity: what the card draws, and what its buttons send.

Every command leaves as an intent the Companion app broadcasts on the phone,
which is the one route that reaches the app whether it is open, in the
background or closed. Nothing here waits for an answer: the app's own push
comes back through the webhook a moment later and is what the card then
shows.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.media_player import (
    BrowseError,
    BrowseMedia,
    MediaClass,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
    RepeatMode,
)
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_call_later
from homeassistant.util import dt as dt_util

from . import ResonusConfigEntry, ResonusData
from .const import ACTION_COMMAND, DOMAIN, PACKAGE, STALE_AFTER_SECONDS
from .subsonic import SubsonicError

SUPPORT = (
    MediaPlayerEntityFeature.PLAY
    | MediaPlayerEntityFeature.PAUSE
    | MediaPlayerEntityFeature.STOP
    | MediaPlayerEntityFeature.NEXT_TRACK
    | MediaPlayerEntityFeature.PREVIOUS_TRACK
    | MediaPlayerEntityFeature.SEEK
    | MediaPlayerEntityFeature.VOLUME_SET
    | MediaPlayerEntityFeature.SHUFFLE_SET
    | MediaPlayerEntityFeature.REPEAT_SET
    | MediaPlayerEntityFeature.PLAY_MEDIA
    | MediaPlayerEntityFeature.BROWSE_MEDIA
)

# What a browsed row turns into when it is played.
PLAY_COMMANDS = {
    "album": "play_album",
    "playlist": "play_playlist",
    "artist": "play_artist",
    MediaType.MUSIC: "play_song",
    "track": "play_song",
}

# The directories the browser opens with, none of which is a thing to play.
ROOT_ROWS = (
    ("playlists", "Playlists", MediaClass.PLAYLIST),
    ("artists", "Artists", MediaClass.ARTIST),
    ("albums", "Albums", MediaClass.ALBUM),
    ("favorites", "Favourites", MediaClass.TRACK),
)

REPEAT_TO_HA = {"off": RepeatMode.OFF, "all": RepeatMode.ALL, "one": RepeatMode.ONE}
REPEAT_FROM_HA = {RepeatMode.OFF: "off", RepeatMode.ALL: "all", RepeatMode.ONE: "one"}


async def async_setup_entry(
    hass: HomeAssistant, entry: ResonusConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([ResonusMediaPlayer(entry)])


class ResonusMediaPlayer(MediaPlayerEntity):
    """One phone running Resonus."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_media_content_type = MediaType.MUSIC
    _attr_supported_features = SUPPORT

    def __init__(self, entry: ResonusConfigEntry) -> None:
        self._entry = entry
        self._data: ResonusData = entry.runtime_data
        self._attr_unique_id = entry.entry_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Resonus",
        )

    async def async_added_to_hass(self) -> None:
        @callback
        def updated() -> None:
            self.async_write_ha_state()
            self._arm_stale_timer()

        self._data.listeners.append(updated)
        self.async_on_remove(lambda: self._data.listeners.remove(updated))
        self.async_on_remove(self._cancel_stale_timer)

    _stale_timer: CALLBACK_TYPE | None = None

    @callback
    def _arm_stale_timer(self) -> None:
        """
        A state that says idle after an hour is only seen when the entity is
        written, and nothing writes it on its own once the phone goes quiet;
        so the write is booked, and booked again with every push.
        """
        self._cancel_stale_timer()
        self._stale_timer = async_call_later(
            self.hass, STALE_AFTER_SECONDS + 1, lambda _now: self.async_write_ha_state()
        )

    @callback
    def _cancel_stale_timer(self) -> None:
        if self._stale_timer:
            self._stale_timer()
            self._stale_timer = None

    # ── What the card draws ──────────────────────────────────────────────

    @property
    def state(self) -> MediaPlayerState:
        state = self._data.state
        # The app pushes on a change and says nothing in between, so a phone
        # that has gone quiet for an hour is not still playing: it is away.
        if (dt_util.utcnow() - state.updated_at).total_seconds() > STALE_AFTER_SECONDS:
            return MediaPlayerState.IDLE
        if state.playing:
            return MediaPlayerState.PLAYING
        return MediaPlayerState.PAUSED if state.song_id else MediaPlayerState.IDLE

    @property
    def media_title(self) -> str | None:
        return self._data.state.title or None

    @property
    def media_artist(self) -> str | None:
        return self._data.state.artist or None

    @property
    def media_album_name(self) -> str | None:
        return self._data.state.album or None

    @property
    def media_content_id(self) -> str | None:
        return self._data.state.song_id or None

    @property
    def media_duration(self) -> int | None:
        return self._data.state.duration or None

    @property
    def media_position(self) -> int | None:
        return self._data.state.position

    @property
    def media_position_updated_at(self):
        return self._data.state.updated_at

    @property
    def volume_level(self) -> float:
        return self._data.state.volume

    @property
    def shuffle(self) -> bool:
        return self._data.state.shuffle

    @property
    def repeat(self) -> RepeatMode:
        return REPEAT_TO_HA.get(self._data.state.repeat, RepeatMode.OFF)

    @property
    def media_image_remotely_accessible(self) -> bool:
        return False

    @property
    def media_image_url(self) -> str | None:
        """
        Never fetched, since `async_get_media_image` below answers instead:
        what Home Assistant does with this is hash it, to know when the cover
        it holds is of another song. So it carries no credentials.
        """
        cover = self._data.state.cover_art or self._data.state.song_id
        return f"{self._data.client.url}/rest/getCoverArt?id={cover}" if cover else None

    async def async_get_media_image(self) -> tuple[bytes | None, str | None]:
        """The cover, fetched with the server's credentials, never handed out."""
        cover = self._data.state.cover_art or self._data.state.song_id
        if not cover:
            return None, None
        picture = await self._data.client.cover_art(cover)
        return picture if picture else (None, None)

    # ── What its buttons send ────────────────────────────────────────────

    async def _command(self, command: str, **extras: str) -> None:
        """
        One intent, through the Companion app on the phone. The extras go as
        `key:value` pairs, which is the only shape `command_broadcast_intent`
        takes.
        """
        pairs = ",".join(f"{key}:{value}" for key, value in {"command": command, **extras}.items())
        await self.hass.services.async_call(
            "notify",
            self._data.notify_service,
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

    async def async_media_play(self) -> None:
        await self._command("play")

    async def async_media_pause(self) -> None:
        await self._command("pause")

    async def async_media_stop(self) -> None:
        await self._command("stop")

    async def async_media_next_track(self) -> None:
        await self._command("next")

    async def async_media_previous_track(self) -> None:
        await self._command("previous")

    async def async_media_seek(self, position: float) -> None:
        await self._command("seek", position=str(int(position)))

    async def async_set_volume_level(self, volume: float) -> None:
        await self._command("volume", level=f"{volume:.2f}")

    async def async_set_shuffle(self, shuffle: bool) -> None:
        await self._command("shuffle", on="true" if shuffle else "false")

    async def async_set_repeat(self, repeat: RepeatMode) -> None:
        await self._command("repeat", mode=REPEAT_FROM_HA.get(repeat, "off"))

    async def async_play_media(self, media_type: str, media_id: str, **kwargs: Any) -> None:
        """A row from the browser, or a `media_content_id` written by hand."""
        kind, _, identifier = media_id.partition("/")
        if kind == "favorites":
            await self._command("play_favorites")
            return
        if kind == "random":
            await self._command("play_random")
            return
        command = PLAY_COMMANDS.get(kind) or PLAY_COMMANDS.get(media_type)
        if not command or not identifier:
            raise HomeAssistantError(f"Resonus cannot play {media_type} {media_id}")
        await self._command(command, id=identifier)

    # ── The browser ──────────────────────────────────────────────────────

    async def async_browse_media(
        self, media_content_type: str | None = None, media_content_id: str | None = None
    ) -> BrowseMedia:
        try:
            return await self._browse(media_content_id)
        except SubsonicError as err:
            raise BrowseError(f"Resonus could not read the library: {err}") from err

    async def async_get_browse_image(
        self, media_content_type: str, media_content_id: str, media_image_id: str | None = None
    ) -> tuple[bytes | None, str | None]:
        """A row's cover, fetched with the server's credentials, for the proxy."""
        if not media_image_id:
            return None, None
        picture = await self._data.client.cover_art(media_image_id, size=300)
        return picture if picture else (None, None)

    def _thumbnail(self, row: dict[str, Any], media_content_id: str) -> str | None:
        """
        The row's cover as an address on this entity's image proxy. Subsonic
        names the cover apart from the thing it belongs to, and that name is
        what the proxy is asked for.
        """
        cover = row.get("coverArt")
        if not cover:
            return None
        return self.get_browse_image_url(MediaType.MUSIC, media_content_id, media_image_id=str(cover))

    async def _browse(self, media_content_id: str | None) -> BrowseMedia:
        if not media_content_id or media_content_id == "library":
            return self._directory(
                "library",
                "Resonus",
                MediaClass.DIRECTORY,
                [
                    BrowseMedia(
                        media_class=media_class,
                        media_content_id=kind,
                        media_content_type=MediaType.MUSIC,
                        title=title,
                        can_play=kind == "favorites",
                        can_expand=True,
                    )
                    for kind, title, media_class in ROOT_ROWS
                ],
            )

        kind, _, identifier = media_content_id.partition("/")
        client = self._data.client

        if kind == "playlists":
            rows = await client.playlists()
            return self._directory(
                "playlists",
                "Playlists",
                MediaClass.DIRECTORY,
                [self._playlist_row(row) for row in rows],
            )
        if kind == "playlist":
            playlist = await client.playlist(identifier)
            return self._directory(
                media_content_id,
                playlist.get("name", "Playlist"),
                MediaClass.PLAYLIST,
                [self._track_row(song) for song in playlist.get("entry") or []],
                playable=True,
            )
        if kind == "artists":
            rows = await client.artists()
            return self._directory(
                "artists",
                "Artists",
                MediaClass.DIRECTORY,
                [self._artist_row(row) for row in rows],
            )
        if kind == "artist":
            artist = await client.artist(identifier)
            return self._directory(
                media_content_id,
                artist.get("name", "Artist"),
                MediaClass.ARTIST,
                [self._album_row(album) for album in artist.get("album") or []],
                playable=True,
            )
        if kind == "albums":
            rows = await client.albums()
            return self._directory(
                "albums",
                "Albums",
                MediaClass.DIRECTORY,
                [self._album_row(row) for row in rows],
            )
        if kind == "album":
            album = await client.album(identifier)
            return self._directory(
                media_content_id,
                album.get("name", "Album"),
                MediaClass.ALBUM,
                [self._track_row(song) for song in album.get("song") or []],
                playable=True,
            )
        if kind == "favorites":
            starred = await client.starred()
            return self._directory(
                "favorites",
                "Favourites",
                MediaClass.DIRECTORY,
                [self._track_row(song) for song in starred.get("song") or []],
                playable=True,
            )
        raise BrowseError(f"Resonus cannot browse {media_content_id}")

    def _directory(
        self,
        media_content_id: str,
        title: str,
        media_class: MediaClass,
        children: list[BrowseMedia],
        *,
        playable: bool = False,
    ) -> BrowseMedia:
        """An opened folder: what it is, and every row in it."""
        return BrowseMedia(
            media_class=media_class,
            media_content_id=media_content_id,
            media_content_type=MediaType.MUSIC,
            title=title,
            can_play=playable,
            can_expand=True,
            children=children,
            children_media_class=children[0].media_class if children else None,
        )

    def _playlist_row(self, row: dict[str, Any]) -> BrowseMedia:
        return BrowseMedia(
            media_class=MediaClass.PLAYLIST,
            media_content_id=f"playlist/{row.get('id')}",
            thumbnail=self._thumbnail(row, f"playlist/{row.get('id')}"),
            media_content_type=MediaType.PLAYLIST,
            title=row.get("name", ""),
            can_play=True,
            can_expand=True,
        )

    def _artist_row(self, row: dict[str, Any]) -> BrowseMedia:
        return BrowseMedia(
            media_class=MediaClass.ARTIST,
            media_content_id=f"artist/{row.get('id')}",
            thumbnail=self._thumbnail(row, f"artist/{row.get('id')}"),
            media_content_type=MediaType.ARTIST,
            title=row.get("name", ""),
            can_play=True,
            can_expand=True,
        )

    def _album_row(self, row: dict[str, Any]) -> BrowseMedia:
        return BrowseMedia(
            media_class=MediaClass.ALBUM,
            media_content_id=f"album/{row.get('id')}",
            thumbnail=self._thumbnail(row, f"album/{row.get('id')}"),
            media_content_type=MediaType.ALBUM,
            title=row.get("name", ""),
            can_play=True,
            can_expand=True,
        )

    def _track_row(self, row: dict[str, Any]) -> BrowseMedia:
        return BrowseMedia(
            media_class=MediaClass.TRACK,
            media_content_id=f"track/{row.get('id')}",
            thumbnail=self._thumbnail(row, f"track/{row.get('id')}"),
            media_content_type=MediaType.MUSIC,
            title=row.get("title", ""),
            can_play=True,
            can_expand=False,
        )
