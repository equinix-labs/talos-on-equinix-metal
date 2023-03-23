#!/usr/bin/env bash

# Disabling the eipTag, https://github.com/equinix/cloud-provider-equinix-metal
# As it interferes with the Talos control plane
SECRET_DATA="cloud-sa.json=$(echo '{"apiKey":"", "projectID":"", "eipTag":"", "eipHealthCheckUseHostIP": true }' | jq -c ".apiKey = \"${PACKET_API_KEY}\" | .projectID = \"${PROJECT_ID}\" ")"
mkdir -p ${TOEM_SECRETS_DIR}/cpem
kubectl create -o yaml --dry-run='client' secret generic -n kube-system metal-cloud-config --from-literal="${SECRET_DATA}" | yq 'del(.metadata.creationTimestamp)' > ${TOEM_SECRETS_DIR}/cpem/cpem.yaml