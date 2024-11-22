import requests
import re
import os
from collections import defaultdict

DOCKERHUB_REPO = "library/nextcloud"
VERSION_REGEX = re.compile(r"((28|29|([3-9][0-9]))([.0-9]*)-)?apache")


def fetch_dockerhub_digests():
    """Ruft alle amd64-Digests von Docker Hub ab und sortiert sie nach Tags."""
    url = f"https://registry.hub.docker.com/v2/repositories/{DOCKERHUB_REPO}/tags?page_size=100"
    all_digests = defaultdict(list)

    while url:
        response = requests.get(url)
        if response.status_code != 200:
            print(f"Fehler beim Abrufen der Daten: {response.status_code}")
            break

        data = response.json()
        for tag_info in data.get("results", []):
            tag_name = tag_info["name"]

            # Regex-Filterung der relevanten Tags
            if not VERSION_REGEX.fullmatch(tag_name):
                continue

            # Suche nach amd64-Digest
            amd64_image = next(
                (image for image in tag_info["images"] if image["architecture"] == "amd64"),
                None
            )
            if amd64_image:
                digest = amd64_image["digest"]
                all_digests[digest].append(tag_name)

        # Nächste Seite abrufen, falls vorhanden
        url = data.get("next")

    return all_digests


def fetch_existing_ghcr_digests():
    """Ruft alle Digests von GHCR ab."""
    headers = {
        "Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
        "Accept": "application/vnd.github.v3+json"
    }
    url = f"https://ghcr.io/v2/{GITHUB_USERNAME}/docker-all-nextcloud-smb/tags/list"
    response = requests.get(url, headers=headers)

    if response.status_code != 200:
        print(f"Fehler beim Abrufen der GHCR-Tags: {response.status_code}")
        return set()

    tags = response.json().get("tags", [])
    existing_digests = set()

    for tag in tags:
        # Manifeste abrufen, um den Digest zu finden
        manifest_url = f"https://ghcr.io/v2/{GITHUB_USERNAME}/docker-all-nextcloud-smb/manifests/{tag}"
        manifest_response = requests.get(manifest_url, headers=headers)
        if manifest_response.status_code == 200:
            description = manifest_response.json().get("description", "")
            if "Original Digest:" in description:
                original_digest = description.split("Original Digest:")[1].strip()
                existing_digests.add(original_digest)

    return existing_digests


def main():
    dockerhub_digests = fetch_dockerhub_digests()
    ghcr_digests = fetch_existing_ghcr_digests()

    # Finde Digests, die gebaut werden müssen
    digests_to_build = {
        digest: tags for digest, tags in dockerhub_digests.items()
        if digest not in ghcr_digests
    }

    print("Neue Images, die gebaut werden müssen:")
    for digest, tags in digests_to_build.items():
        print(f"Digest: {digest}")
        print(f"Tags: {', '.join(tags)}")

    # Baue und pushe Images
    for digest, tags in digests_to_build.items():
        for tag in tags:
            print(f"Baue und pushe Image für Tag: {tag}, Digest: {digest}")
            os.system(
                f"docker build --build-arg BASE_IMAGE_DIGEST={digest} -t ghcr.io/{GITHUB_USERNAME}/docker-all-nextcloud-smb:{tag} ."
            )
            os.system(
                f"docker push ghcr.io/{GITHUB_USERNAME}/docker-all-nextcloud-smb:{tag}"
            )


if __name__ == "__main__":
    main()
