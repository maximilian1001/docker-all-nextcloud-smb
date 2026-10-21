# Nextcloud (apache) with the PHP smbclient extension for SMB/CIFS external storage.
# BASE is set by the workflow to a digest-pinned upstream image, e.g.
#   docker.io/library/nextcloud@sha256:...
ARG BASE=docker.io/library/nextcloud:stable-apache
FROM ${BASE}

LABEL org.opencontainers.image.title="nextcloud-smb" \
      org.opencontainers.image.description="Official Nextcloud apache image with the PHP smbclient extension" \
      org.opencontainers.image.source="https://github.com/maximilian1001/docker-all-nextcloud-smb" \
      org.opencontainers.image.licenses="AGPL-3.0-or-later"

# smbclient/libsmbclient stay installed (runtime + headers), build tools that
# were not already part of the base image ($PHPIZE_DEPS) are removed again.
RUN set -eux; \
    savedAptMark="$(apt-mark showmanual)"; \
    apt-get update; \
    apt-get install -y --no-install-recommends $PHPIZE_DEPS smbclient libsmbclient-dev; \
    pecl install smbclient; \
    docker-php-ext-enable smbclient; \
    apt-mark auto '.*' > /dev/null; \
    apt-mark manual $savedAptMark smbclient libsmbclient-dev > /dev/null; \
    apt-get purge -y --auto-remove -o APT::AutoRemove::RecommendsImportant=false; \
    rm -rf /var/lib/apt/lists/* /tmp/pear ~/.pearrc; \
    php -m | grep -qix smbclient
