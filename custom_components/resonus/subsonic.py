"""
The library, read straight from the Subsonic server (Navidrome, or the
Navifind proxy in front of it).

The integration browses with these credentials rather than asking the phone:
the media browser has to answer while the phone's screen is off, and a phone
is not a server. What the phone is asked for is only to play something, which
goes the other way, through an intent.

Only the handful of endpoints the browser needs are here, all of them
`GET /rest/<view>` with the same query, answering JSON.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from typing import Any

from aiohttp import ClientSession, ClientTimeout

TIMEOUT = ClientTimeout(total=15)
CLIENT = "ha-resonus"
API_VERSION = "1.16.1"
# The most Navidrome answers per page, and how many pages are worth asking.
PAGE = 500
MAX_ALBUMS = 20_000
# How many of each a search answers with: enough to find the one meant,
# few enough to read on a card.
SEARCH_ARTISTS = 10
SEARCH_ALBUMS = 10
SEARCH_SONGS = 25


class SubsonicError(Exception):
    """The server refused, or answered something that is not an answer."""


@dataclass(frozen=True)
class Credentials:
    """Where the library is and who is asking."""

    url: str
    username: str
    password: str


class SubsonicClient:
    """One server, for as long as the config entry lives."""

    def __init__(self, session: ClientSession, credentials: Credentials) -> None:
        self._session = session
        self._credentials = credentials

    @property
    def url(self) -> str:
        return self._credentials.url

    def _query(self) -> dict[str, str]:
        """
        The credentials as Subsonic takes them: a salt, and the password
        hashed with it. Never the password itself, which the API does still
        accept and which would sit in every log a proxy keeps.
        """
        salt = secrets.token_hex(8)
        token = hashlib.md5(f"{self._credentials.password}{salt}".encode()).hexdigest()
        return {
            "u": self._credentials.username,
            "t": token,
            "s": salt,
            "v": API_VERSION,
            "c": CLIENT,
            "f": "json",
        }

    async def call(self, view: str, **params: Any) -> dict[str, Any]:
        """One request, with its `subsonic-response` unwrapped."""
        query = self._query()
        query.update({k: str(v) for k, v in params.items() if v is not None})
        url = f"{self._credentials.url}/rest/{view}"
        try:
            async with self._session.get(url, params=query, timeout=TIMEOUT) as res:
                if res.status != 200:
                    raise SubsonicError(f"HTTP {res.status}")
                payload = await res.json(content_type=None)
        except SubsonicError:
            raise
        except Exception as err:  # noqa: BLE001 - the cause is in the message
            raise SubsonicError(str(err)) from err
        body = (payload or {}).get("subsonic-response") or {}
        if body.get("status") != "ok":
            message = (body.get("error") or {}).get("message", "refused")
            raise SubsonicError(message)
        return body

    async def ping(self) -> None:
        """Whether the address and the credentials hold. Raises if they do not."""
        await self.call("ping")

    async def playlists(self) -> list[dict[str, Any]]:
        body = await self.call("getPlaylists")
        return (body.get("playlists") or {}).get("playlist") or []

    async def playlist(self, playlist_id: str) -> dict[str, Any]:
        body = await self.call("getPlaylist", id=playlist_id)
        return body.get("playlist") or {}

    async def artists(self) -> list[dict[str, Any]]:
        body = await self.call("getArtists")
        indexes = (body.get("artists") or {}).get("index") or []
        return [artist for index in indexes for artist in index.get("artist") or []]

    async def artist(self, artist_id: str) -> dict[str, Any]:
        body = await self.call("getArtist", id=artist_id)
        return body.get("artist") or {}

    async def album(self, album_id: str) -> dict[str, Any]:
        body = await self.call("getAlbum", id=album_id)
        return body.get("album") or {}

    async def albums(self, kind: str = "alphabeticalByName") -> list[dict[str, Any]]:
        """
        Every album, a page at a time: the server hands out five hundred at
        most per ask, and a library is easily more. Capped all the same, so
        a server that ignores the offset cannot be asked for ever.
        """
        albums: list[dict[str, Any]] = []
        for offset in range(0, MAX_ALBUMS, PAGE):
            body = await self.call("getAlbumList2", type=kind, size=PAGE, offset=offset)
            page = (body.get("albumList2") or {}).get("album") or []
            albums.extend(page)
            if len(page) < PAGE:
                break
        return albums

    async def search(self, query: str) -> dict[str, Any]:
        """Artists, albums and songs matching, as `search3` groups them."""
        body = await self.call(
            "search3",
            query=query,
            artistCount=SEARCH_ARTISTS,
            albumCount=SEARCH_ALBUMS,
            songCount=SEARCH_SONGS,
        )
        return body.get("searchResult3") or {}

    async def starred(self) -> dict[str, Any]:
        body = await self.call("getStarred2")
        return body.get("starred2") or {}

    async def cover_art(self, cover_id: str, size: int = 600) -> tuple[bytes, str] | None:
        """
        The picture itself, fetched here rather than handed to the browser as
        a URL: the URL would carry the credentials to every dashboard open on
        the house.
        """
        query = self._query()
        query.update({"id": cover_id, "size": str(size)})
        url = f"{self._credentials.url}/rest/getCoverArt"
        try:
            async with self._session.get(url, params=query, timeout=TIMEOUT) as res:
                if res.status != 200:
                    return None
                content_type = res.headers.get("Content-Type", "image/jpeg")
                if "json" in content_type:
                    return None
                return await res.read(), content_type
        except Exception:  # noqa: BLE001 - a missing cover is not an error
            return None
