# Docker Nextcloud images (apache versions) with installed smbclient
Nextcloud publishes in the [official repo](https://hub.docker.com/_/nextcloud) only the base versions, but no images with pre-installed smbclient. However, this is required to connect SMB/CIFS storage as external storage.

This repo contains all apache docker images for nextcloud with installed smbclient.

## Using the image
The apache image contains a webserver and exposes port 80. To start the container type:

```bash
$ docker run -d -p 8080:80 ghcr.io/maximilian1001/docker-all-nextcloud-smb:apache
```
Now you can access Nextcloud at http://localhost:8080/⁠ from your host system.

## Understanding the labels
The tags of the original versions are adopted unchanged by nextcloud. Check the [Nextcloud Docker Hub Documentation](https://hub.docker.com/_/nextcloud#:~:text=Supported%20tags%20and%20respective%20Dockerfile%20links) to learn more about the tags.

Use the ```apache```-tag, to get the latest version.

## How does it work?
The original images are taken and the following commands (see Dockerfile) are executed to install smbclient:
```bash
apt-get update && apt-get install -y smbclient libsmbclient-dev && rm -rf /var/lib/apt/lists/*
pecl install smbclient
echo "extension=smbclient.so" >> /usr/local/etc/php/conf.d/nextcloud.ini
```