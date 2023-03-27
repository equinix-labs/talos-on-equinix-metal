#!/usr/bin/env bash

TOEM_CP_ENDPOINT="$(yq '.[0]' "${TOEM_PROJECT_ROOT}/secrets/ip-addresses.yaml" | cut -d "/" -f 1)"
helm upgrade --install --namespace kube-system --set k8sServiceHost="${TOEM_CP_ENDPOINT}" cilium ./