FROM livekit/livekit-server:v1.7.2

# The upstream image is distroless-ish; we add bash + envsubst so the
# entrypoint can render the config from /shared secrets.
USER root
RUN apk add --no-cache bash gettext

COPY livekit.yaml.tmpl /pureprivacy/livekit.yaml.tmpl
COPY entrypoint.sh /pureprivacy/entrypoint.sh
RUN chmod 0755 /pureprivacy/entrypoint.sh

EXPOSE 7880 7881 50000-50019/udp

ENTRYPOINT ["/pureprivacy/entrypoint.sh"]
