#!/usr/bin/env bash

mkdir -p "${TOEM_MANIFEST_DIR}"

clusterctl generate cluster "${CLUSTER_NAME}" --from templates/cluster-talos-template.yaml > "${TOEM_MANIFEST_DIR}/${CLUSTER_NAME}.yaml"
cd "${TOEM_SECRETS_DIR}"
yq -s '"spec_" + .kind' "${TOEM_PROJECT_ROOT}/${TOEM_MANIFEST_DIR}/${CLUSTER_NAME}.yaml"
yq e '. | .spec.controlPlaneConfig.controlplane.configPatches[0].value.contents |= load_str("cpem/cpem.yaml")' -i spec_TalosControlPlane.yml
yq eval-all spec_* > "${CLUSTER_NAME}.yaml"
cd "${TOEM_PROJECT_ROOT}"

echo "k8s_yaml('${TOEM_SECRETS_DIR}/${CLUSTER_NAME}.yaml')" > Tiltfile

#tilt up --port 10351