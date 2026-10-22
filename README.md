# Docker Nextcloud images (apache versions) with installed smbclient

Nextcloud publishes in the [official repo](https://hub.docker.com/_/nextcloud) only the base versions, but no images with the PHP `smbclient` extension. This extension is required to connect SMB/CIFS storage as external storage.

This repo rebuilds the official **apache** images with `smbclient` and publishes them under the **same tags** to
`ghcr.io/maximilian1001/docker-all-nextcloud-smb` (linux/amd64 only).

## Using the image
The apache image contains a webserver and exposes port 80:

```bash
docker run -d -p 8080:80 ghcr.io/maximilian1001/docker-all-nextcloud-smb:34-apache
```
Now you can access Nextcloud at http://localhost:8080/ from your host system.
Everything else (volumes, environment variables, cron, upgrades) works exactly as described in the [official documentation](https://github.com/nextcloud/docker).

## Supported tags
The newest release of every major version from **30** up to the major version that upstream `stable-apache` currently points to,
published under all of its official apache tags:

| Tag | Meaning |
|---|---|
| `NN-apache` (e.g. `34-apache`) | newest release of a major version – **recommended** |
| `NN.N-apache`, `NN.N.N-apache` | the same image under its minor / exact patch tag (e.g. `34.0-apache`, `34.0.5-apache`) |
| `stable-apache`, `production-apache` | same image as upstream `stable-apache` / `production-apache` |

A new major version (e.g. 35) is only added once upstream `stable-apache` points to it.
`apache` and `latest` are **not** published: upstream they point to the newest major, which is usually newer than stable,
and they would quickly become stale or flip between majors here.
Older minor/patch releases of a major are not built (tags published earlier stay on GHCR but are no longer updated).
fpm and other variants are not built.

> **Upgrades:** Nextcloud can only be upgraded **one major version at a time** (e.g. 32 → 33 → 34).
> Pin your deployment to a major tag like `34-apache` and move to the next major deliberately,
> instead of following `stable-apache`, which jumps to the next major without warning.

Every image carries the OCI labels `org.opencontainers.image.base.name` and `org.opencontainers.image.base.digest`
with the exact upstream image it was built from.

## How does it work?
The workflow [`.github/workflows/build.yml`](.github/workflows/build.yml) runs daily:

1. **Discover** ([`.github/scripts/discover.py`](.github/scripts/discover.py)): reads all upstream apache tags from Docker Hub,
   groups them by their linux/amd64 digest, determines the major version of `stable-apache` and keeps the newest group (`NN-apache`) of each major.
   A group is built only if one of its tags is missing on GHCR or its `base.digest` label differs from the upstream digest.
2. **Build**: one build per upstream digest, based on `nextcloud@sha256:<digest>` (pinned), see [`Dockerfile`](Dockerfile):
   ```bash
   apt-get install -y --no-install-recommends $PHPIZE_DEPS smbclient libsmbclient-dev
   pecl install smbclient-1.2.0dev.tgz   # downloaded from pecl.php.net
   docker-php-ext-enable smbclient
   # build-only packages are removed again, apt lists and pear cache are cleaned
   ```
3. **Smoke test**: `php -m` must list `smbclient`, then all tags of the group are pushed.
4. **Cleanup**: untagged image versions on GHCR are deleted (tagged versions are kept).

On Sundays the newest image of every major version is rebuilt to pick up Debian security updates.

Manual runs (*Actions → Build and Push to GHCR → Run workflow*):

| Input | Effect |
|---|---|
| `tags` | only build the groups of these upstream tags, e.g. `31.0.14-apache,34-apache` |
| `force` | rebuild every image in range |
| `dry_run` | only show the build matrix in the job summary |

Dependabot keeps the GitHub Actions up to date, and the weekly run re-enables the workflow via the API so that GitHub does not disable the schedule after 60 days without commits.
