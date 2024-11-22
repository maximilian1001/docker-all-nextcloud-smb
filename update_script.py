import requests
import os
from collections import defaultdict
import re

DOCKERHUB_REPO = "library/nextcloud"
GITHUB_USERNAME = "maximilian1001"
GITHUB_REPO = "docker-all-nextcloud-smb"
TAG_FILTER_REGEX = r"((28|29|([3-9][0-9]))([.0-9]*)-)?apache"

def fetch_dockerhub_images():
    """Fetch all amd64 images from Docker Hub, grouped by digest."""
    url = f"https://registry.hub.docker.com/v2/repositories/{DOCKERHUB_REPO}/tags"
    params = {"page_size": 100}
    images_by_digest = defaultdict(list)
    
    print("Fetching images from Docker Hub...")
    
    while url:
        response = requests.get(url, params=params)
        if response.status_code != 200:
            print(f"Error fetching Docker Hub tags: {response.status_code}")
            return {}

        data = response.json()
        for result in data.get("results", []):
            tag_name = result["name"]

            # Filter tags based on the regex
            if not re.match(TAG_FILTER_REGEX, tag_name):
                continue

            # Search for amd64 architecture in images
            for image in result.get("images", []):
                if image["architecture"] == "amd64":
                    digest = image["digest"]
                    images_by_digest[digest].append(tag_name)
                    break

        # Next page URL for pagination
        url = data.get("next")

    print(f"Found {len(images_by_digest)} unique amd64 digests.")
    return images_by_digest

def build_and_push_images(images_by_digest):
    """Build and push Docker images grouped by digest."""
    headers = {
        "Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
        "Accept": "application/vnd.github.v3+json"
    }

    for digest, tags in images_by_digest.items():
        print(f"Building image for digest: {digest}")
        print(f"Tags: {', '.join(tags)}")

        # Modify the Dockerfile to include the original digest in the description
        with open("Dockerfile", "w") as dockerfile:
            dockerfile.write(f"""
            FROM nextcloud:{tags[0]}

            RUN apt-get update && apt-get install -y smbclient libsmbclient-dev
            RUN pecl install smbclient
            RUN echo "extension=smbclient.so" >> /usr/local/etc/php/conf.d/nextcloud.ini
            """)

        # Build the Docker image
        image_name = f"ghcr.io/{GITHUB_USERNAME}/{GITHUB_REPO}:{tags[0]}"
        build_command = f"docker build -t {image_name} ."
        print(f"Running build command: {build_command}")
        os.system(build_command)

        # Push the Docker image
        for tag in tags:
            full_image_name = f"ghcr.io/{GITHUB_USERNAME}/{GITHUB_REPO}:{tag}"
            os.system(f"docker tag {image_name} {full_image_name}")
            push_command = f"docker push {full_image_name}"
            print(f"Pushing image: {full_image_name}")
            os.system(push_command)

def main():
    images_by_digest = fetch_dockerhub_images()
    if not images_by_digest:
        print("No images found to build.")
        return

    build_and_push_images(images_by_digest)

if __name__ == "__main__":
    main()
