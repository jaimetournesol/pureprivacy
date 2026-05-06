FROM ghcr.io/element-hq/lk-jwt-service:0.2.0 AS upstream

FROM alpine:3.20

# ca-certificates so we can append the synapse-fed-proxy CA at startup.
# update-ca-certificates is the proper way to install a new root.
RUN apk add --no-cache ca-certificates

COPY --from=upstream /lk-jwt-service /lk-jwt-service
COPY entrypoint.sh /pureprivacy/entrypoint.sh
RUN chmod 0755 /pureprivacy/entrypoint.sh /lk-jwt-service

EXPOSE 8082

ENTRYPOINT ["/pureprivacy/entrypoint.sh"]
