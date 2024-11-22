import requests
import os
import re
import subprocess
from collections import defaultdict

GITHUB_USERNAME = "maximilian1001"
GHCR_REPO = f"ghcr.io/{GITHUB_USERNAME}/docker-all-nextcloud-smb"
VERSION_REGEX = r"((([3-9][0-9]))([.0-9]*)-)?apache"

def fetch_dockerhub_tags_and_digests():
    """Ruft alle Tags und zugehörigen Digests von Docker Hub ab und gruppiert sie nach Digest."""
    url = "https://registry.hub.docker.com/v2/repositories/library/nextcloud/tags?page_size=100"
    grouped_tags = defaultdict(list)

    while url:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()

        for result in data["results"]:
            tag = result["name"]
            digest = result["digest"]
            if re.match(VERSION_REGEX, tag):
                grouped_tags[digest].append(tag)

        url = data.get("next")
    return grouped_tags

def fetch_existing_ghcr_digests():
    """Ruft alle Digests von GHCR ab."""
    url = f"https://ghcr.io/v2/{GITHUB_USERNAME}/docker-all-nextcloud-smb/tags/list"
    headers = {"Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}"}
    response = requests.get(url, headers=headers)
    if response.status_code != 200:
        print(f"Error fetching GHCR tags: {response.status_code}")
        return set()

    tags = response.json().get("tags", [])
    existing_digests = set()

    for tag in tags:
        manifest_url = f"https://ghcr.io/v2/{GITHUB_USERNAME}/docker-all-nextcloud-smb/manifests/{tag}"
        response = requests.get(manifest_url, headers=headers)
        if response.status_code == 200:
            description = response.json().get("description", "")
            if "Original Digest:" in description:
                original_digest = description.split("Original Digest:")[1].strip()
                existing_digests.add(original_digest)

    return existing_digests

def build_and_push_by_digest(grouped_tags, existing_digests):
    """Baut Images für neue Digests und pusht sie unter allen zugehörigen Tags."""
    for digest, tags in grouped_tags.items():
        if digest in existing_digests:
            print(f"Skipping Digest {digest}, already exists in GHCR.")
            continue

        print(f"\nBuilding and pushing image for Digest: {digest}")
        try:
            # Docker-Build-Befehl
            subprocess.run(
                f"docker build . -t {GHCR_REPO}:{tags[0]} --build-arg VERSION={tags[0]}",
                shell=True,
                check=True,
            )

            # Push für jeden Tag
            for tag in tags:
                print(f"Pushing tag: {tag}")
                subprocess.run(
                    f"docker tag {GHCR_REPO}:{tags[0]} {GHCR_REPO}:{tag}",
                    shell=True,
                    check=True,
                )
                subprocess.run(
                    f"docker push {GHCR_REPO}:{tag} --description 'Original Digest: {digest}'",
                    shell=True,
                    check=True,
                )

        except subprocess.CalledProcessError as e:
            print(f"Error during build or push for Digest {digest}: {e}")
            continue

        # Cleanup nach jedem erfolgreichen Push
        print(f"Cleaning up local Docker artifacts for Digest: {digest}")
        try:
            # Löscht das lokal gebaute Image
            subprocess.run(f"docker rmi {GHCR_REPO}:{tags[0]}", shell=True, check=True)
            subprocess.run("docker system prune -af", shell=True, check=True)
        except subprocess.CalledProcessError as e:
            print(f"Error during cleanup for Digest {digest}: {e}")

if __name__ == "__main__":
    print("Fetching Docker Hub tags and digests...")
    grouped_tags = fetch_dockerhub_tags_and_digests()
    print(f"Found {len(grouped_tags)} unique digests matching the criteria.")

    print("Fetching existing GHCR digests...")
    existing_digests = fetch_existing_ghcr_digests()
    print(f"Found {len(existing_digests)} digests already in GHCR.")

    print("\nStarting build and push process...")
    build_and_push_by_digest(grouped_tags, existing_digests)
    print("Process complete.")
