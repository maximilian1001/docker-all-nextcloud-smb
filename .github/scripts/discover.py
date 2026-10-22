#!/usr/bin/env python3
"""Discover which Nextcloud apache images need to be (re)built.

Reads the upstream tags of docker.io/library/nextcloud (linux/amd64 only),
groups them by their amd64 manifest digest and keeps, for every major version
between MIN_MAJOR and the major version `stable-apache` points to, only the
newest release (the group carrying the `NN-apache` tag, together with its
`NN.N-apache` / `NN.N.N-apache` aliases). Older minor/patch releases are not
built.
For every group it checks the already published image on GHCR: a group is
built only if one of its tags is missing or carries a different
`org.opencontainers.image.base.digest` label.

Only the Python standard library is used. Any network or parsing error makes
the script fail (non-zero exit), so a broken discovery never silently skips or
mass-builds images.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

UPSTREAM_REPO = "library/nextcloud"
HUB_TAGS_URL = (
    "https://hub.docker.com/v2/namespaces/library/repositories/nextcloud/tags"
)
MIN_MAJOR = 30
STABLE_TAG = "stable-apache"
# Alias tags that follow `stable-apache` and are therefore always in range.
ALIAS_TAGS = ("stable-apache", "production-apache")
# `apache` / `latest` point to the newest release, which is usually newer than
# stable. They are intentionally never published (see README).
VERSION_TAG_RE = re.compile(r"^(\d+)(?:\.(\d+)(?:\.(\d+))?)?-apache$")
ARCH = "amd64"
TIMEOUT = 30
RETRIES = 3

MANIFEST_ACCEPT = ", ".join(
    [
        "application/vnd.oci.image.index.v1+json",
        "application/vnd.docker.distribution.manifest.list.v2+json",
        "application/vnd.oci.image.manifest.v1+json",
        "application/vnd.docker.distribution.manifest.v2+json",
    ]
)


class DiscoverError(RuntimeError):
    pass


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def http_get(url: str, headers: dict | None = None, allow_404: bool = False):
    """GET with timeout and simple retry. Returns (headers, body) or None on 404."""
    last_err: Exception | None = None
    for attempt in range(1, RETRIES + 1):
        req = urllib.request.Request(url, headers=headers or {})
        req.add_header("User-Agent", "docker-all-nextcloud-smb-discover")
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                return resp.headers, resp.read()
        except urllib.error.HTTPError as err:
            if err.code == 404 and allow_404:
                return None
            if err.code in (429, 500, 502, 503, 504):
                last_err = err
            else:
                raise DiscoverError(f"GET {url} failed: HTTP {err.code}") from err
        except (urllib.error.URLError, TimeoutError) as err:
            last_err = err
        time.sleep(2 * attempt)
    raise DiscoverError(f"GET {url} failed after {RETRIES} attempts: {last_err}")


def get_json(url: str, headers: dict | None = None, allow_404: bool = False):
    res = http_get(url, headers, allow_404)
    if res is None:
        return None
    try:
        return json.loads(res[1])
    except json.JSONDecodeError as err:
        raise DiscoverError(f"invalid JSON from {url}") from err


# --------------------------------------------------------------------------
# Upstream (Docker Hub)
# --------------------------------------------------------------------------


def parse_version(tag: str):
    """'34.0.5-apache' -> (34, 0, 5); '34-apache' -> (34,); else None."""
    m = VERSION_TAG_RE.match(tag)
    if not m:
        return None
    return tuple(int(p) for p in m.groups() if p is not None)


def fetch_upstream_tags() -> dict[str, str]:
    """Return {tag: amd64 manifest digest} for all relevant upstream tags."""
    url = HUB_TAGS_URL + "?" + urllib.parse.urlencode(
        {"page_size": 100, "name": "apache"}
    )
    result: dict[str, str] = {}
    pages = 0
    while url:
        data = get_json(url)
        pages += 1
        if pages > 200:
            raise DiscoverError("Docker Hub pagination did not terminate")
        for item in data.get("results", []):
            name = item.get("name", "")
            if name not in ALIAS_TAGS and parse_version(name) is None:
                continue
            for image in item.get("images") or []:
                if (
                    image.get("os") == "linux"
                    and image.get("architecture") == ARCH
                    and image.get("digest")
                ):
                    result[name] = image["digest"]
                    break
        url = data.get("next")
    log(f"Docker Hub: {len(result)} relevant tags with {ARCH} image ({pages} pages)")
    return result


@dataclass
class Group:
    digest: str
    tags: list[str] = field(default_factory=list)

    @property
    def version_tags(self):
        return [t for t in self.tags if parse_version(t) is not None]

    @property
    def major(self) -> int | None:
        majors = {parse_version(t)[0] for t in self.version_tags}
        if len(majors) > 1:
            raise DiscoverError(f"digest {self.digest} has several majors: {self.tags}")
        return majors.pop() if majors else None

    @property
    def primary(self) -> str:
        """Most specific version tag, e.g. 34.0.5-apache."""
        return max(self.version_tags, key=lambda t: (len(parse_version(t)), parse_version(t)))

    @property
    def sort_key(self):
        v = parse_version(self.primary)
        return v + (0,) * (3 - len(v))


def tag_sort_key(tag: str):
    v = parse_version(tag)
    if v is None:
        return (1, (), tag)  # aliases last
    return (0, tuple(-x for x in v), tag)


def build_groups(upstream: dict[str, str]):
    if STABLE_TAG not in upstream:
        raise DiscoverError(f"upstream tag {STABLE_TAG} not found")
    by_digest: dict[str, Group] = {}
    for tag, digest in upstream.items():
        by_digest.setdefault(digest, Group(digest)).tags.append(tag)

    stable_group = by_digest[upstream[STABLE_TAG]]
    stable_major = stable_group.major
    if stable_major is None:
        raise DiscoverError(f"{STABLE_TAG} shares no digest with a version tag")
    if stable_major < MIN_MAJOR:
        raise DiscoverError(f"{STABLE_TAG} major {stable_major} < {MIN_MAJOR}")

    groups = []
    for group in by_digest.values():
        major = group.major
        if major is None:
            log(f"skip digest {group.digest}: only alias tags {group.tags}")
            continue
        if not MIN_MAJOR <= major <= stable_major:
            continue
        if f"{major}-apache" not in group.tags:
            continue  # older minor/patch release of this major
        group.tags.sort(key=tag_sort_key)
        groups.append(group)
    groups.sort(key=lambda g: g.sort_key)
    missing = sorted(set(range(MIN_MAJOR, stable_major + 1)) - {g.major for g in groups})
    if missing:
        raise DiscoverError(f"no upstream NN-apache tag for major(s) {missing}")
    return groups, stable_major


# --------------------------------------------------------------------------
# Published images (GHCR)
# --------------------------------------------------------------------------


class Registry:
    def __init__(self, host: str, repo: str, token: str | None = None):
        self.host = host
        self.repo = repo
        self.basic = token
        self._bearer = None
        self._config_cache: dict[str, dict] = {}

    def bearer(self) -> str:
        if self._bearer is None:
            headers = {}
            if self.basic:
                cred = base64.b64encode(f"token:{self.basic}".encode()).decode()
                headers["Authorization"] = f"Basic {cred}"
            url = f"https://{self.host}/token?" + urllib.parse.urlencode(
                {"scope": f"repository:{self.repo}:pull", "service": self.host}
            )
            data = get_json(url, headers)
            self._bearer = data.get("token") or data.get("access_token")
            if not self._bearer:
                raise DiscoverError(f"no registry token from {self.host}")
        return self._bearer

    def _get(self, path: str, accept: str | None = None, allow_404=False):
        headers = {"Authorization": f"Bearer {self.bearer()}"}
        if accept:
            headers["Accept"] = accept
        return get_json(f"https://{self.host}/v2/{self.repo}/{path}", headers, allow_404)

    def base_digest(self, tag: str) -> str | None:
        """Return the base.digest label of tag, '' if unlabeled, None if missing."""
        manifest = self._get(f"manifests/{tag}", MANIFEST_ACCEPT, allow_404=True)
        if manifest is None:
            return None
        if "manifests" in manifest:  # index: pick linux/amd64
            for entry in manifest["manifests"]:
                plat = entry.get("platform") or {}
                if plat.get("os") == "linux" and plat.get("architecture") == ARCH:
                    manifest = self._get(f"manifests/{entry['digest']}", MANIFEST_ACCEPT)
                    break
            else:
                return ""
        cfg_digest = manifest["config"]["digest"]
        if cfg_digest not in self._config_cache:
            self._config_cache[cfg_digest] = self._get(f"blobs/{cfg_digest}")
        labels = (self._config_cache[cfg_digest].get("config") or {}).get("Labels") or {}
        return labels.get("org.opencontainers.image.base.digest", "")


def published_state(registry: Registry, tags: list[str]) -> dict[str, str | None]:
    with ThreadPoolExecutor(max_workers=8) as pool:
        return dict(zip(tags, pool.map(registry.base_digest, tags)))


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------


def write_output(path: str | None, key: str, value: str) -> None:
    if not path:
        return
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(f"{key}={value}\n")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--image", default="ghcr.io/maximilian1001/docker-all-nextcloud-smb")
    ap.add_argument("--tags", default="", help="comma separated upstream tags to build")
    ap.add_argument("--force", action="store_true", help="rebuild every group in range")
    ap.add_argument(
        "--rebuild-latest",
        action="store_true",
        help="rebuild the newest group of every major (weekly OS updates)",
    )
    ap.add_argument("--github-output", default=os.environ.get("GITHUB_OUTPUT"))
    ap.add_argument("--summary", default=os.environ.get("GITHUB_STEP_SUMMARY"))
    args = ap.parse_args()

    upstream = fetch_upstream_tags()
    groups, stable_major = build_groups(upstream)
    log(f"stable-apache -> major {stable_major}; {len(groups)} groups in range "
        f"{MIN_MAJOR}..{stable_major}")

    host, _, repo = args.image.partition("/")
    registry = Registry(host, repo, os.environ.get("REGISTRY_TOKEN") or None)
    all_tags = [t for g in groups for t in g.tags]
    state = published_state(registry, all_tags)

    requested = [t.strip() for t in args.tags.split(",") if t.strip()]
    tag_to_group = {t: g for g in groups for t in g.tags}
    unknown = [t for t in requested if t not in tag_to_group]
    if unknown:
        raise DiscoverError(
            f"requested tags not upstream, out of range {MIN_MAJOR}..{stable_major} "
            "or not the newest release of their major: "
            + ", ".join(unknown)
        )
    requested_groups = {id(tag_to_group[t]) for t in requested}
    newest_per_major = {id(g) for g in groups if f"{g.major}-apache" in g.tags}

    include, rows = [], []
    for g in groups:
        missing = [t for t in g.tags if state[t] is None]
        unlabeled = [t for t in g.tags if state[t] == ""]
        stale = [t for t in g.tags if state[t] and state[t] != g.digest]
        if requested:
            reason = "requested" if id(g) in requested_groups else ""
        elif args.force:
            reason = "force"
        elif missing:
            reason = "missing: " + ", ".join(missing)
        elif stale:
            reason = "upstream changed: " + ", ".join(stale)
        elif unlabeled:
            reason = "no base.digest label: " + ", ".join(unlabeled)
        elif args.rebuild_latest and id(g) in newest_per_major:
            reason = "weekly rebuild"
        else:
            reason = ""
        rows.append((g, reason))
        if reason:
            include.append(
                {
                    "tag": g.primary,
                    "major": g.major,
                    "digest": g.digest,
                    "tags": ",".join(g.tags),
                    "reason": reason,
                }
            )

    if len(include) > 256:
        raise DiscoverError(f"{len(include)} builds exceed the matrix limit of 256")

    matrix = json.dumps({"include": include}, separators=(",", ":"))
    write_output(args.github_output, "matrix", matrix)
    write_output(args.github_output, "count", str(len(include)))
    write_output(args.github_output, "stable_major", str(stable_major))

    lines = [
        "## Discovery",
        "",
        f"`{STABLE_TAG}` points to major **{stable_major}** -> range "
        f"**{MIN_MAJOR}..{stable_major}**, {len(groups)} upstream digests, "
        f"**{len(include)} to build**.",
        "",
        "| Build | Tags | Upstream digest (amd64) | Reason |",
        "|---|---|---|---|",
    ]
    for g, reason in rows:
        lines.append(
            f"| {'yes' if reason else 'no'} | {', '.join(f'`{t}`' for t in g.tags)} "
            f"| `{g.digest[:19]}` | {reason or 'up to date'} |"
        )
    text = "\n".join(lines) + "\n"
    if args.summary:
        with open(args.summary, "a", encoding="utf-8") as fh:
            fh.write(text)
    print(text)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except DiscoverError as err:
        print(f"::error::{err}", flush=True)
        sys.exit(1)
