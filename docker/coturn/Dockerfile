FROM coturn/coturn:4.6.2-r12-alpine

USER root
RUN apk add --no-cache bash gettext

COPY turnserver.conf.tmpl /pureprivacy/turnserver.conf.tmpl
COPY entrypoint.sh /pureprivacy/entrypoint.sh
RUN chmod 0755 /pureprivacy/entrypoint.sh

EXPOSE 3478 5349 49152-49161
ENTRYPOINT ["/pureprivacy/entrypoint.sh"]
