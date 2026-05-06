FROM alpine:3.20

RUN apk add --no-cache \
        bash \
        tor \
        tini

# Tor runs as the unprivileged `tor` user shipped with the alpine package.
# The hidden-service directory must be 0700 owned by that user or tor refuses
# to start.  We chown in the entrypoint because the volume mount may not
# match at build time.

COPY torrc /etc/tor/torrc
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod 0755 /usr/local/bin/entrypoint.sh

VOLUME ["/var/lib/tor"]

EXPOSE 9050

ENTRYPOINT ["/sbin/tini", "--", "/usr/local/bin/entrypoint.sh"]
