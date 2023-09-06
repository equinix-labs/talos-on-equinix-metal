#!/usr/bin/env bash

mkdocs build
docker buildx build --push \
--platform linux/amd64,linux/arm64 \
--tag harbor.v1.gocy.org/demo/gocy:$(git rev-parse --short HEAD) .