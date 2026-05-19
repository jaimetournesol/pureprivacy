# Running two PurePrivacy instances on the same host

You can run a second PurePrivacy install side-by-side on the same
machine.  Both instances mint their own onions, share Tor for inter-box
federation, and don't see each other's containers, networks, or
volumes.  The two stacks have to differ on **four** things:

| Variable                  | Why                                              |
|---------------------------|--------------------------------------------------|
| `COMPOSE_PROJECT_NAME`    | container, network, and volume namespaces        |
| `PUREPRIVACY_NET_PREFIX`  | static IPs the compose hands out to services    |
| `PUREPRIVACY_SUBNET`      | the docker bridge's /24 — must not overlap      |
| `WIZARD_PORT` + `MCP_PORT`| loopback host ports — can't share with another instance |

Anything else (image tags, MCP grace window, voice profile) is
per-instance and unrelated.

## Recipe

```bash
# Clone a fresh working copy next to the first.
cd ~/work
git clone https://github.com/jaimetournesol/pureprivacy pureprivacy-b
cd pureprivacy-b

# Write a .env for this instance.  The four variables above are the
# whole story; everything else inherits the defaults from .env.example.
cat > .env <<'EOF'
COMPOSE_PROJECT_NAME=pureprivacy-b
PUREPRIVACY_NET_PREFIX=172.31.0
PUREPRIVACY_SUBNET=172.31.0.0/24
WIZARD_PORT=8090
MCP_PORT=8091
EOF

# Bring it up.  --dev only matters if you edited a Dockerfile; the
# normal `init` path pulls the same pre-built images as instance A.
./scripts/pureprivacy init -y --dev
```

Now `pureprivacy status` from either working directory targets that
directory's stack — the CLI picks up `COMPOSE_PROJECT_NAME` from the
local `.env` and uses `${PROJECT}-tor`, `${PROJECT}-wizard`, etc. for
`docker exec`.  `pureprivacy info` on each side gives you the local
onion and bearer.

## Pairing the two

Once both stacks report 7/7 healthy:

```bash
# In instance A's working dir
pureprivacy pair create
# → copy the printed pair code

# In instance B's working dir
pureprivacy pair accept <code from A>

# Now do the reverse:
pureprivacy pair create     # in B
pureprivacy pair accept <code from B>   # in A
```

The wizard updates `federation_domain_whitelist` and restarts Synapse
on each side.  After that, `@alice:<onion-A>` can invite
`@bob:<onion-B>` into a federated room, and federation traffic rides
Tor between the two local stacks — exactly as it would across two
physically separate boxes.

## Resource shape

A second instance roughly doubles the host's RAM and disk footprint —
plan for ~2 GB RAM and ~5 GB disk per instance during steady state.
Both stacks run their own Synapse, Postgres, and Tor; there's no
shared infrastructure between them, by design.

## Cleanup

```bash
cd pureprivacy-b
pureprivacy down            # stop containers, keep volumes
pureprivacy reset           # destroy everything (asks for confirmation)
rm -rf ../pureprivacy-b     # only after `reset` if you want the working dir gone too
```
