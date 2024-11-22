# Dockerfile
ARG VERSION=latest  # Fallback-Version
FROM nextcloud:${VERSION}

RUN apt-get update && apt-get install -y smbclient libsmbclient-dev && rm -rf /var/lib/apt/lists/*
RUN pecl install smbclient
RUN echo "extension=smbclient.so" >> /usr/local/etc/php/conf.d/nextcloud.ini