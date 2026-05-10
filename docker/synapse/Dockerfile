# hadolint global ignore=DL3002
# DL3002 (last USER should not be root) is deliberately suppressed:
# the upstream Synapse image expects to run as root and gosu-drops to
# the `synapse` user via its own /start.py entrypoint.  Our wrapper
# also needs root to render homeserver.yaml from the template and
# (on first boot) generate the signing key under /data.  The effective
# hardening lives in docker-compose.yml — cap_drop:ALL + a minimal
# init-caps cap_add — which makes in-container root harmless on the
# host.  Hadolint can't see the compose-level controls.

ARG SYNAPSE_IMAGE_TAG=v1.122.0
FROM ghcr.io/element-hq/synapse:${SYNAPSE_IMAGE_TAG}

# The upstream image runs as root and drops to the `synapse` user via its own
# entrypoint.  We add bash + curl for healthchecks and our wrapper.
USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        bash \
        curl \
        gettext-base \
    && rm -rf /var/lib/apt/lists/*

COPY homeserver.yaml.tmpl /pureprivacy/homeserver.yaml.tmpl
COPY log.config /pureprivacy/log.config
COPY render_config.py /pureprivacy/render_config.py
COPY entrypoint.sh /pureprivacy/entrypoint.sh
RUN chmod 0755 /pureprivacy/entrypoint.sh

ENTRYPOINT ["/pureprivacy/entrypoint.sh"]
