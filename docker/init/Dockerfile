FROM alpine:3.20

RUN apk add --no-cache \
        bash \
        coreutils \
        openssl

COPY init.sh /usr/local/bin/init.sh
RUN chmod 0755 /usr/local/bin/init.sh

ENTRYPOINT ["/usr/local/bin/init.sh"]
