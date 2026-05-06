# Connecting your agent (MCP integration)

PurePrivacy ships an MCP server that exposes nine tools your agent can use
to read and write your messages on your behalf.  Any framework that speaks
the [Model Context Protocol](https://modelcontextprotocol.io) can attach.

## What you need to plug into your agent

Both `pureprivacy init` and the wizard summary at `http://127.0.0.1:8088`
print the same three values:

```
MCP endpoint:  http://127.0.0.1:8089/mcp
Bearer token:  c30bf127254c6d719d95de7c346650d808d787afc2514f7503a0615ae3fc24f3
Bot Matrix ID: @pureprivacy-mcp:abc...d.onion
```

Save the bearer token somewhere your agent's config can read it.  It's
your write-key to the bot — anyone with this token can post messages as
the bot user.

If you lose track later, `pureprivacy info --secrets` re-displays the
bearer (along with the admin password and recovery key).

## Letting the bot see a room

The MCP bot only sees rooms you explicitly invite it to.  In Element
(the original — recommended for v0.1):

1. Open the room.
2. Tap the room name → *People & invites* → *Invite*.
3. Paste the bot's Matrix ID (`@pureprivacy-mcp:...onion`).
4. The bot auto-joins within a couple of seconds.

(Element X is similar — *room name → People → Invite* — but see
[docs/phone-setup.md](phone-setup.md) for why the original Element is
the recommended client in v0.1.)

For end-to-end encrypted rooms, you also need to **verify the bot's
device**.  Element will show a verification prompt the first time you
encounter the bot in an E2EE room — tap it and confirm.  Without
verification, the bot won't receive the Megolm session keys and
`get_room_history` / `search_messages` will return empty for that room.

The bot's device identity is stable across container restarts — the
session and Olm key store persist in the `pureprivacy_mcp_data` volume,
so you verify once.  If that volume is lost, the bot logs in again with
a fresh device ID and you'll be re-prompted.

> **Coming in v0.2:** opt-in auto-trust (`pureprivacy init --trust-bot`),
> which pre-stages cross-signing so verification reduces to entering your
> Element recovery key once.  v0.1 ships the foundation (stable
> identity, persistent Olm store) but leaves the verification tap manual.

## Tool surface

| Tool                | Purpose                                                                |
|---------------------|------------------------------------------------------------------------|
| `list_rooms`        | All rooms the bot is in.                                               |
| `list_unread`       | Rooms with unread messages.                                            |
| `get_room_history`  | Last N messages in a room (max 200).                                   |
| `search_messages`   | Server-side full-text search across decrypted messages.                |
| `get_room_members`  | User IDs and display names for a room.                                 |
| `send_message`      | Post a plain-text or HTML-formatted message.                           |
| `mark_read`         | Move the read marker forward.                                          |
| `upload_file`       | Upload a file from inside the MCP container as an `m.file` event.      |
| `download_file`     | Download an `mxc://` URI to disk inside the MCP container.             |

## Claude Code

```bash
claude mcp add pureprivacy http://127.0.0.1:8089/mcp \
  --transport http \
  --header "Authorization: Bearer <token-from-wizard>"
```

Then `claude` will auto-discover the tools.  Try it:

> *"Show me the unread rooms on PurePrivacy."*

## Codex CLI

```bash
codex mcp add pureprivacy \
  --url http://127.0.0.1:8089/mcp \
  --header "Authorization=Bearer <token>"
```

(`codex mcp` syntax has been moving — if the above doesn't work in your
Codex version, run `codex mcp --help` to see the current flags.)

## Cursor

Open *Settings → Features → MCP* and add a custom server:

```json
{
  "mcpServers": {
    "pureprivacy": {
      "url": "http://127.0.0.1:8089/mcp",
      "transport": "http",
      "headers": {
        "Authorization": "Bearer <token>"
      }
    }
  }
}
```

## Cline

Cline reads `~/.config/cline/cline_mcp_settings.json`:

```json
{
  "mcpServers": {
    "pureprivacy": {
      "type": "streamableHttp",
      "url": "http://127.0.0.1:8089/mcp",
      "headers": {
        "Authorization": "Bearer <token>"
      }
    }
  }
}
```

## Anything else

The endpoint speaks the [MCP Streamable HTTP transport](https://modelcontextprotocol.io/specification/2025-06-18/basic/transports).
Any compliant client works.  Authentication is bearer token in the
`Authorization` header — see [SECURITY.md](../SECURITY.md) for caveats.

## Reaching the MCP from another machine

By default the MCP port is bound to `127.0.0.1`, so only the operator's
own host can hit it.  If you want a remote agent to reach it:

- Expose it as a Tor onion service.  Edit `docker/tor/torrc` and add
  `HiddenServicePort 8089 172.30.0.1:8089` (using the gateway IP for the
  docker network).  Your remote agent reaches it through Tor like any
  other onion service.

PurePrivacy is Tor-only by design; do not bind the MCP port to a public
interface — there is no built-in TLS terminator for it, and the bearer
token alone is not sufficient protection on the open internet.

## Rotating the bearer token

Open the wizard summary at `http://127.0.0.1:8088` and click
**Rotate MCP token**.  The new token is generated and written atomically
to the shared volume; the MCP server picks it up on its next request, so
no container restart is needed.

**Grace window.** The previous token stays valid for 10 minutes after a
rotation so already-deployed agents can keep working while you migrate
them.  The wizard surfaces a countdown ("Previous token still accepted
for 9 min 42 s") and a *Revoke previous token now* button for the
"the old token leaked, kill it now" case.

You can change the grace window with the `MCP_TOKEN_GRACE_SECONDS` env
var in `.env` (default 600).  Set it to 1 to effectively disable the
grace window, but agents will start seeing `403`s on their next call.
