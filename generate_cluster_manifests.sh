#!/usr/bin/env bash

# https://www.talos.dev/v1.3/talos-guides/install/bare-metal-platforms/equinix-metal/#passing-in-the-configuration-as-user-data
SED_OPTIONS='1s/^/#!talos\n/'
mkdir -p "${TOEM_MANIFEST_DIR}"

clusterctl generate cluster "${CLUSTER_NAME}" --from templates/cluster-talos-template.yaml > "${TOEM_MANIFEST_DIR}/${CLUSTER_NAME}.yaml"
cd "${TOEM_SECRETS_DIR}"

yq -s '"spec_" + .kind + "_" + .metadata.name' "${TOEM_PROJECT_ROOT}/${TOEM_MANIFEST_DIR}/${CLUSTER_NAME}.yaml"
yq e '. | .spec.controlPlaneConfig.controlplane.configPatches[0].value.contents |= load_str("cpem/cpem.yaml")' -i spec_TalosControlPlane_talos-alloy-102-control-plane.yml
yq eval-all spec_* > "${CLUSTER_NAME}.yaml"
yq '... comments=""' "${CLUSTER_NAME}.yaml" > "${CLUSTER_NAME}-no-comment.yaml"


if [ ! -f secrets/talosconfig ]; then
	talosctl gen config "${CLUSTER_NAME}" "https://${TOEM_CP_ENDPOINT}:6443"
fi
talosWorker="worker.yaml"
talosControl="controlplane.yaml"
sed -i '' "${SED_OPTIONS}" "${talosWorker}"
sed -i '' "${SED_OPTIONS}" "${talosControl}"
# In our case configs are useless without https://www.talos.dev/v1.3/talos-guides/install/bare-metal-platforms/equinix-metal/#passing-in-the-configuration-as-user-data
cp worker.yaml worker-vanilla.yaml
cp controlplane.yaml controlplane-vanilla.yaml

yq e '.cluster.externalCloudProvider.enabled = true | .cluster.externalCloudProvider.manifests[0] = "https://github.com/equinix/cloud-provider-equinix-metal/releases/download/v3.5.0/deployment.yaml"' -i "${talosWorker}"
yq e '.cluster.externalCloudProvider.enabled = true | .cluster.externalCloudProvider.manifests[0] = "https://github.com/equinix/cloud-provider-equinix-metal/releases/download/v3.5.0/deployment.yaml"' -i "${talosControl}"
yq e '.cluster.apiServer.extraArgs.cloud-provider = "external"' -i "${talosControl}"
yq e '.cluster.controllerManager.extraArgs.cloud-provider = "external"' -i "${talosControl}"
## shellcheck disable=SC2016
#yq e '.cluster.kubelet.extraArgs.cloud-provider = "external" | .cluster.kubelet.extraArgs.provider-id = "\"equinixmetal://{{ `{{ v1.instance_id }}` }}\" "' -i "${talosControl}"
## shellcheck disable=SC2016
#yq e '.cluster.kubelet.extraArgs.cloud-provider = "external" | .cluster.kubelet.extraArgs.provider-id = "\"equinixmetal://{{ `{{ v1.instance_id }}` }}\" "' -i "${talosWorker}"
yq e '.cluster.inlineManifests[0] = {"name":"cpem-secret", "contents":load_str("cpem/cpem.yaml")}' -i "${talosControl}"
yq '... comments=""' "${talosWorker}" > "worker-no-comment.yaml"
yq '... comments=""' "${talosControl}" > "controlplane-no-comment.yaml"
sed -i '' "${SED_OPTIONS}" "worker-no-comment.yaml"
sed -i '' "${SED_OPTIONS}" "controlplane-no-comment.yaml"

yq e ' del(.spec.controlPlaneConfig.controlplane.configPatches) | .spec.controlPlaneConfig.controlplane.generateType = "none" | .spec.controlPlaneConfig.controlplane.data = load_str("controlplane-no-comment.yaml")' -i spec_TalosControlPlane_talos-alloy-102-control-plane.yml
yq e ' del(.spec.template.spec.configPatches) | .spec.template.spec.generateType = "none" | .spec.template.spec.data = load_str("worker-no-comment.yaml")' -i spec_TalosConfigTemplate_talos-alloy-102-worker.yml
yq eval-all spec_* > "${CLUSTER_NAME}-static-config.yaml"
yq '... comments=""' "${CLUSTER_NAME}-static-config.yaml" > "${CLUSTER_NAME}-static-config-no-comment.yaml"


rm spec_*
cd "${TOEM_PROJECT_ROOT}"

gfind secrets -regex  '.*\(controlplane\|worker\).*' -exec bash -c "echo {}:; talosctl validate -m cloud -c {}" \;

#echo "k8s_yaml('${TOEM_SECRETS_DIR}/${CLUSTER_NAME}.yaml')" > Tiltfile
#tilt up --port 10351