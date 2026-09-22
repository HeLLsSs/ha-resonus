"""Names shared across the integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "resonus"

# What the config flow asks for.
DEFAULT_NAME: Final = "Resonus"
CONF_NAME: Final = "name"
CONF_NOTIFY_SERVICE: Final = "notify_service"
CONF_WEBHOOK_ID: Final = "webhook_id"

# The app's side of the wire (docs/INTENTS.md in the Resonus repository).
PACKAGE: Final = "com.hellsss.resonuls"
ACTION_COMMAND: Final = f"{PACKAGE}.COMMAND"

# A phone that has said nothing for this long is taken to be away rather than
# still playing what it last pushed: the app only pushes on a change, so a
# phone switched off would otherwise leave a track playing on the card for
# ever.
STALE_AFTER_SECONDS: Final = 60 * 60
