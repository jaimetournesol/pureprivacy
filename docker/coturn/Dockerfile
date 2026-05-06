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
