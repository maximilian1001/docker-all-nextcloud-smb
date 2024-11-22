import requests
import subprocess
import os
import re

GITHUB_USERNAME = "maximilian1001"
GHCR_REPO = f"ghcr.io/{GITHUB_USERNAME}/docker-all-nextcloud-smb"

# Regulärer Ausdruck für die Versionsfilterung
VERSION_REGEX = r"((28|29|([3-9][0-9]))([.0-9]*)-)?apache"

def get_nextcloud_versions():
    """Ruft alle verfügbaren Nextcloud-Versionen von Docker Hub ab."""
    url = "https://registry.hub.docker.com/v2/repositories/library/nextcloud/tags?page_size=100"
    versions = []
    while url:
        response = requests.get(url)
        data = response.json()
        for result in data["results"]:
            tag = result["name"]
            if re.match(VERSION_REGEX, tag):
                versions.append(tag)
        url = data.get("next")
    return versions

def get_existing_ghcr_versions():
    """Ruft alle bereits veröffentlichten Versionen aus GHCR ab."""
    url = f"https://ghcr.io/v2/{GITHUB_USERNAME}/docker-all-nextcloud-smb/tags/list"
    headers = {"Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}"}
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        data = response.json()
        return data.get("tags", [])
    else:
        print(f"Error fetching GHCR tags: {response.status_code}")
        return []

def build_and_push_images(new_versions):
    """Baut und pusht neue Docker-Images zu GHCR."""
    for version in new_versions:
        print(f"Building and pushing image for Nextcloud version: {version}")
        os.system(f"docker build . -t {GHCR_REPO}:{version} --build-arg VERSION={version}")
        os.system(f"docker push {GHCR_REPO}:{version}")

if __name__ == "__main__":
    nextcloud_versions = get_nextcloud_versions()
    existing_versions = get_existing_ghcr_versions()

    # Nur neue Versionen filtern
    new_versions = [v for v in nextcloud_versions if v not in existing_versions]

    if new_versions:
        print(f"New versions to build: {new_versions}")
        build_and_push_images(new_versions)
    else:
        print("No new versions found.")
