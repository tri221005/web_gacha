#!/usr/bin/env bash
# Build va push image Docker len GitHub Container Registry (mien phi, 10GB).
#
#   bash deploy/build_push.sh <ten-github-user>
#
# GHCR khong can token rieng: dung Personal Access Token voi quyen "write:
# packages" hoac dung `docker login ghcr.io -u <user> --password-stdin` voi
# token do.
set -euo pipefail

GITHUB_USER="${1:?Dung: bash deploy/build_push.sh <ten-github-user>}"
IMAGE="ghcr.io/${GITHUB_USER}/jellyvale-web"
TAG="${TAG:-latest}"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "==> Build $IMAGE:$TAG"
cd "$ROOT_DIR"
docker build -t "${IMAGE}:${TAG}" -t "${IMAGE}:latest" .

echo "==> Push $IMAGE:$TAG"
docker push "${IMAGE}:${TAG}"
docker push "${IMAGE}:latest"

echo
echo "Xong. Tren VPS dung image:"
echo "  IMAGE=${IMAGE}:${TAG}"
echo
echo "Neu chua login GHCR, chay:"
echo "  echo \$GHCR_TOKEN | docker login ghcr.io -u ${GITHUB_USER} --password-stdin"
