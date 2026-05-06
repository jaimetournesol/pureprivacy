FROM caddy:2.8-alpine

# bash for the entrypoint, openssl to mint the self-signed cert lk-jwt
# will trust at startup.
RUN apk add --no-cache bash openssl

COPY entrypoint.sh /pureprivacy/entrypoint.sh
RUN chmod 0755 /pureprivacy/entrypoint.sh

# 80, 443, 8448 are the three ports lk-jwt's matrix:// resolver might land
# on; we serve all three off the same TLS termination back to synapse:8008.
EXPOSE 80 443 8448

ENTRYPOINT ["/pureprivacy/entrypoint.sh"]
