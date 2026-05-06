FROM alpine:3.20

RUN apk add --no-cache privoxy bash

COPY config /etc/privoxy/config

EXPOSE 8118

USER privoxy
ENTRYPOINT ["privoxy", "--no-daemon", "/etc/privoxy/config"]
