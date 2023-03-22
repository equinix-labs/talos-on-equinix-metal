# Hi!

PoC that aims to run [Talos Linux](https://www.talos.dev/) on [Equinix Metal](https://deploy.equinix.com/metal/) with
[Kubernetes Cluster API](https://cluster-api.sigs.k8s.io/)

# Project setup
## prerequisites
- [Equinix Metal](https://deploy.equinix.com/metal/)
- [zsh env](https://github.com/ohmyzsh/ohmyzsh/tree/master/plugins/dotenv) plugin or equivalent 
- [colima](https://github.com/abiosoft/colima) for MacOS users
- [kconf](https://github.com/particledecay/kconf)
- go
- [tilt](https://tilt.dev/)
- [kind](https://kind.sigs.k8s.io/)
- kubectl
- [clusterctl](https://cluster-api.sigs.k8s.io/clusterctl/overview.html)
- [Metal CLI](https://github.com/equinix/metal-cli/#installation)
- [talosctl](https://github.com/siderolabs/talos)

## experiment
We will mix [CABPT](https://github.com/siderolabs/cluster-api-bootstrap-provider-talos), [CACPPT](https://github.com/siderolabs/cluster-api-control-plane-provider-talos), [CAPP](https://github.com/kubernetes-sigs/cluster-api-provider-packet). 
This development setup is *somewhat equivalent* to
```sh
clusterctl init -b talos -c talos -i packet
```
but with tilt for better log visibility, version might vary. For additional instructions consider: 
- https://github.com/kubernetes-sigs/cluster-api-provider-packet
- https://github.com/siderolabs/cluster-api-templates

## flow
### Make sure you have the submodules
### Examine and adjust [.env](.env)
### Create the tilt-settings.json file in the cluster-api folder.
```sh
touch cluster-api/tilt-settings.json 
```

### Copy the following into that file, updating the <> sections with relevant info:
```json
{
    "default_registry": "ghcr.io/<your github username>",
    "provider_repos": ["../cluster-api-provider-packet", "../cluster-api-bootstrap-provider-talos", "../cluster-api-control-plane-provider-talos"],
    "enable_providers": ["packet","talos-bootstrap","talos-control-plane"],
    "kustomize_substitutions": {
        "PACKET_API_KEY": "<API_KEY>",
        "PROJECT_ID": "<PROJECT_ID>",
        "EXP_CLUSTER_RESOURCE_SET": "true",
        "EXP_MACHINE_POOL": "true",
        "CLUSTER_TOPOLOGY": "true"
    }
}
```

### Create a cluster.
#### Navigate to the cluster-api directory
```sh
make tilt-up
```
#### Get another terminal window, navigate to the repository root
##### Generate [CPEM](https://github.com/equinix/cloud-provider-equinix-metal) secret
```shell
./generate_cpem_secret.sh
```
```shell
./generate_cluster_manifests.sh
```

#### Benchmark
Using talosctl and metal cli as described in the [official guide] (https://www.talos.dev/v1.3/talos-guides/install/bare-metal-platforms/equinix-metal/), with a twist.
The cluster endpoint is configured as VIP attached to the control plane node.
```shell
metal device create \
  --project-id $PROJECT_ID \
  --facility $FACILITY \
  --operating-system "talos_v1" \
  --plan $PLAN\
  --hostname toem-test-cp-1\
  --userdata-file secrets/controlplane.yaml
```
```shell
metal device create \
  --project-id $PROJECT_ID \
  --facility $FACILITY \
  --operating-system "talos_v1" \
  --plan $PLAN\
  --hostname toem-test-wo-1\
  --userdata-file secrets/worker.yaml
```
```shell
metal device get -o yaml > secrets/device-list.yaml
```
```shell
export config_plane_ip=$(yq '.[] | select(.hostname == "toem-test-cp-1") | .ip_addresses[] | select(.public == true and .address_family == 4) | .address' secrets/device-list.yaml | head -n 1)
```
```shell
talosctl --talosconfig secrets/talosconfig config endpoint ${config_plane_ip}
talosctl --talosconfig secrets/talosconfig config node ${config_plane_ip}
talosctl --talosconfig secrets/talosconfig bootstrap
talosctl --talosconfig secrets/talosconfig kubeconfig secrets/
```
Use kubeconfig from secrets/kubeconfig to interact with the cluster
```shell
kconf add secrets/kubeconfig
kconf use admin@${CLUSTER_NAME}
```
`kubectl` to hearts content... 

#### static-config
`generate_cluster_manifests.sh` creates a file `secretes/${CLUSTER_NAME}-static-config.yaml`  
with static Talos configuration. This configuration is exactly the same as in case of the benchmark ^. 
```yaml
apiVersion: bootstrap.cluster.x-k8s.io/v1alpha3
kind: TalosConfigTemplate
metadata:
  name: talos-alloy-102-worker
  namespace: default
spec:
  template:
    spec:
      generateType: none
      talosVersion: v1.3.5
      data: |
        #!talos
        version: v1alpha1
        debug: false
        persist: true
```
```yaml
apiVersion: controlplane.cluster.x-k8s.io/v1alpha3
kind: TalosControlPlane
metadata:
  name: talos-alloy-102-control-plane
  namespace: default
spec:
  controlPlaneConfig:
    controlplane:
      generateType: none
      talosVersion: v1.3.5
      data: |
        #!talos
        version: v1alpha1
        debug: false
        persist: true
```
apply with
```shell
kubectl apply -f secrets/${CLUSTER_NAME}-static-config.yaml
```

#### static-config issues
- https://github.com/KrystianMarek/talos-on-equinix-metal/issues/2