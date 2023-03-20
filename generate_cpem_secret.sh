#!/usr/bin/env bash

SECRET_DATA="cloud-sa.json=\"$(echo '{"apiKey": "","projectID": "", "eipTag": "", "eipHealthCheckUseHostIP": true }' | jq -c ".apiKey = \"${PACKET_API_KEY}\" | .projectID = \"${PROJECT_ID}\" | .eipTag=\"cluster-api-provider-packet:cluster-id:${CLUSTER_NAME}\"")\""
mkdir -p ${TOEM_SECRETS_DIR}/cpem
kubectl create -o yaml --dry-run='client' secret generic -n kube-system metal-cloud-config --from-literal="${SECRET_DATA}" | yq 'del(.metadata.creationTimestamp)' > ${TOEM_SECRETS_DIR}/cpem/cpem.yaml