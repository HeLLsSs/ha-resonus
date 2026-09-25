# Resonus for Home Assistant

A `media_player` entity for a phone or tablet running
[Resonus](https://github.com/HeLLsSs/resonus): browse or search the library
from the card, tap an album, and it plays on that device, or on whichever of
the house's speakers the card picked. What it is playing, and where, comes
back to the card.

Nothing is polled. The state and the library are local; the commands go
through the Companion app's notifications, which reach the phone over
Google's push servers unless the Companion app is set to **local push**
(Settings › Companion app › Notifications › push channel: WebSocket). Worth
turning on: it is faster, and it keeps a wall tablet answering when the
internet is down.

## How it works

| Direction | Route |
| --- | --- |
| Home Assistant → the app | A notification to the Companion app, which broadcasts an intent the app answers whether it is open, in the background or closed (`docs/INTENTS.md` in the Resonus repository). |
| The app → Home Assistant | The app pushes what it is playing to a webhook this integration registers, on every change worth a repaint. |
| On a restart | Home Assistant asks the phone to say what it is playing, since the push is one way and it holds nothing across a restart. |
| The library | Read straight from the music server (Navidrome, or the Navifind proxy in front of it), so the browser answers with the phone's screen off. |

## Requirements

- Home Assistant 2025.6 or later; the search field in the media browser
  needs 2026.8 or later.
- Resonus 1.4.0 or later on the device, with **Settings › Home Assistant**
  switched on: that screen shows the webhook identifier this integration asks
  for. Picking a speaker from the card also needs the address and token that
  screen asks for, since the device is what hands the speaker the music.
- The **Home Assistant Companion app** on the same device, so it has a
  `notify.mobile_app_…` service.
- Local push turned on in the Companion app, unless you are happy for every
  button on the card to go around by Google.
- The device excluded from Android's battery optimisation. A wall tablet with
  a music app the system is free to kill is a card that stops answering.

## Setting it up

1. Copy `custom_components/resonus` into your Home Assistant `config`
   directory, or add this repository to HACS as a custom repository.
2. Restart Home Assistant.
3. **Settings › Devices & services › Add integration → Resonus**, and fill in
   a name for the card (the room, say), the music server address and
   credentials, the phone's notify service
   (`mobile_app_tablet`, without the `notify.` in front, is accepted either
   way) and the webhook identifier from the app.

The entity that appears takes the standard media control card:

```yaml
type: media-control
entity: media_player.resonus
```

## What the card can do

Play, pause, stop, next, previous, seek, volume, shuffle, repeat, and browse:
playlists, artists, albums and favourites, down to the track. Playing a
playlist, an album or an artist plays the whole of it; a track plays alone.

**Search** is the field at the top of every directory in the browser, and a
`Search` directory at the root that is nothing but that field: artists first,
then albums, then tracks. Inside the playlists it searches their names.

**Where it plays** is the player's source: the device itself, under the name
given at setup, and every media player in the house a URL can be handed to.
The same choice is a `select` entity, `select.<name>_output`, for a
dashboard that wants the speaker next to the card:

```yaml
type: entities
entities:
  - select.living_room_output
```

Picking a speaker moves the queue there and the device keeps playing it,
one track at a time, as it does from its own output sheet; picking the
device brings the music back. A speaker chosen on the device itself that
Home Assistant has no entity for (a Chromecast or a LinkPlay speaker reached
directly) shows by name and cannot be picked here. The list is read afresh
on every push from the device, so a speaker that has just appeared shows
once the device next says something.

`media_player.play_media` also takes `favorites` and `random` as a
`media_content_id`, for an automation that just wants music on:

```yaml
action: media_player.play_media
target:
  entity_id: media_player.resonus
data:
  media_content_type: music
  media_content_id: random
```

## What it does not do

- **A push from the internet.** The webhook is local only: the address on
  the phone's Home Assistant screen must be the house's own, not a Nabu Casa
  or reverse-proxy one.

- **iOS.** The command half is an Android broadcast intent.
- **Queue editing.** The app owns the queue; the card starts things and
  transports them.
- **Two phones on one identifier.** Each device has its own webhook
  identifier and its own entry here.
