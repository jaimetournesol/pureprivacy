# hadolint global ignore=DL3002
# DL3002 (last USER should not be root) is deliberately suppressed: the
# entrypoint needs root to install bash/envsubst and render the config
# from /shared secrets, and livekit-server itself does not require root
# at runtime.  The effective hardening lives in docker-compose.yml —
# cap_drop:ALL + no-new-privileges:true — which makes in-container root
# harmless on the host.  Hadolint can't see the compose-level controls.

FROM livekit/livekit-server:v1.7.2

# The upstream image is distroless-ish; we add bash + envsubst so the
# entrypoint can render the config from /shared secrets.
USER root
RUN apk add --no-cache bash gettext

COPY livekit.yaml.tmpl /pureprivacy/livekit.yaml.tmpl
COPY entrypoint.sh /pureprivacy/entrypoint.sh
RUN chmod 0755 /pureprivacy/entrypoint.sh

# Tor-only mode: livekit.yaml.tmpl forces TCP relay (UDP cannot ride a
# hidden service), so we deliberately do NOT expose the WebRTC UDP
# range — it would advertise ports that are never bound.
EXPOSE 7880 7881

ENTRYPOINT ["/pureprivacy/entrypoint.sh"]
