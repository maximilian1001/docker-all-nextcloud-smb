import requests
import re
from collections import defaultdict

DOCKERHUB_URL = "https://registry.hub.docker.com/v2/repositories/library/nextcloud/tags"
REGEX = re.compile(r"^((28|29|([3-9][0-9]))([.0-9]*)-)?apache$")
HEADERS = {"Accept": "application/json"}
GITHUB_USERNAME = "maximilian1001"
REPO_NAME = "docker-all-nextcloud-smb"

def fetch_dockerhub_tags():
    """Fetches DockerHub tags and filters by amd64 and regex."""
    page = 1
    tags_by_digest = defaultdict(list)
    print("Fetching DockerHub tags...")

    while True:
        response = requests.get(f"{DOCKERHUB_URL}?page={page}&page_size=100", headers=HEADERS)
        if response.status_code != 200:
            print(f"Error fetching DockerHub tags: {response.status_code}")
            break

        data = response.json()
        for result in data.get("results", []):
            tag_name = result.get("name", "")
            if not REGEX.match(tag_name):
                continue

            # Find amd64 image
            amd64_digest = None
            for image in result.get("images", []):
                if image.get("architecture") == "amd64":
                    amd64_digest = image.get("digest")
                    break

            if amd64_digest:
                tags_by_digest[amd64_digest].append(tag_name)

        # Check for next page
        if not data.get("next"):
            break
        page += 1

    print(f"Fetched {len(tags_by_digest)} digests with matching tags.")
    return tags_by_digest


def fetch_existing_ghcr_digests():
    """Fetch existing digests from GHCR."""
    url = f"https://ghcr.io/v2/{GITHUB_USERNAME}/{REPO_NAME}/tags/list"
    headers = {
        "Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
        "Accept": "application/vnd.github.v3+json"
    }
    response = requests.get(url, headers=headers)

    if response.status_code == 403:
        print("Error: Access to GHCR denied. Check your token permissions.")
        return set()
    elif response.status_code != 200:
        print(f"Error fetching GHCR tags: {response.status_code}")
        return set()

    tags = response.json().get("tags", [])
    print(f"Fetched {len(tags)} existing tags from GHCR.")
    return set(tags)


def build_and_push_images(tags_by_digest, existing_tags):
    """Build and push images for new digests."""
    new_digests = {digest: tags for digest, tags in tags_by_digest.items() if not any(tag in existing_tags for tag in tags)}
    print(f"New digests to process: {len(new_digests)}")

    for digest, tags in new_digests.items():
        print(f"Building image for digest: {digest} with tags: {tags}")
        # Write Dockerfile
        with open("Dockerfile", "w") as dockerfile:
            dockerfile.write(f"FROM nextcloud:{tags[0]}\n")
            dockerfile.write("RUN apt-get update && apt-get install -y smbclient libsmbclient-dev\n")
            dockerfile.write("RUN pecl install smbclient\n")
            dockerfile.write("RUN echo \"extension=smbclient.so\" >> /usr/local/etc/php/conf.d/nextcloud.ini\n")

        # Build and push for each tag
        for tag in tags:
            image_name = f"ghcr.io/{GITHUB_USERNAME}/{REPO_NAME}:{tag}"
            print(f"Building and pushing {image_name}...")
            os.system(f"docker build -t {image_name} .")
            os.system(f"docker push {image_name}")

            # Annotate image with digest information
            os.system(f"docker buildx imagetools inspect {image_name} --annotations 'org.opencontainers.image.description=Original Digest: {digest}'")

        # Clean up Docker artifacts
        os.system("docker system prune -af")

    print("All images built and pushed successfully.")


def main():
    tags_by_digest = fetch_dockerhub_tags()
    existing_tags = fetch_existing_ghcr_digests()
    build_and_push_images(tags_by_digest, existing_tags)


if __name__ == "__main__":
    main()
