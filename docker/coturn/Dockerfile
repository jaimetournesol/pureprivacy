# hadolint global ignore=DL3002
# DL3002 (last USER should not be root) is deliberately suppressed: the
# coturn upstream entrypoint needs root to render /etc/coturn/turn-
# server.conf with envsubst, and turnserver itself drops to a service
# user once it has bound its ports.  The effective hardening lives in
# docker-compose.yml — cap_drop:ALL + no-new-privileges:true plus a
# minimal cap_add list — which makes in-container root harmless on
# the host.  Hadolint can't see the compose-level controls.

FROM coturn/coturn:4.6.2-r12-alpine

USER root
RUN apk add --no-cache bash gettext

COPY turnserver.conf.tmpl /pureprivacy/turnserver.conf.tmpl
COPY entrypoint.sh /pureprivacy/entrypoint.sh
RUN chmod 0755 /pureprivacy/entrypoint.sh

# Listening ports + relay range.  The relay range MUST stay in sync with
# `min-port`/`max-port` in turnserver.conf.tmpl AND with the
# `HiddenServicePort` block in docker/tor/torrc — Tor cannot wildcard-
# map a range, so all three files have to agree.  EXPOSE is metadata
# only (compose does not publish these to the host) but kept accurate
# for tooling and operator-facing `docker inspect` output.
EXPOSE 3478 5349 49152-49191
ENTRYPOINT ["/pureprivacy/entrypoint.sh"]
