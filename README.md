# Resonus for Home Assistant

A `media_player` entity for a phone or tablet running
[Resonus](https://github.com/HeLLsSs/resonus): browse the library from the
card, tap an album, and it plays on that device. What it is playing comes
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

- Resonus 1.3.0 or later on the device, with **Settings › Home Assistant**
  switched on: that screen shows the webhook identifier this integration asks
  for.
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

- **iOS.** The command half is an Android broadcast intent.
- **Queue editing.** The app owns the queue; the card starts things and
  transports them.
- **Two phones on one identifier.** Each device has its own webhook
  identifier and its own entry here.
