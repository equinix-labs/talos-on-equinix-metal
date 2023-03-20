# Hi!

PoC that aims to run [Talos Linux](https://www.talos.dev/) on [Equinix Metal](https://deploy.equinix.com/metal/) with
[Kubernetes Cluster API](https://cluster-api.sigs.k8s.io/)

# Project setup
## prerequisites
- [Equinix Metal](https://deploy.equinix.com/metal/)
- [zsh env](https://github.com/ohmyzsh/ohmyzsh/tree/master/plugins/dotenv) plugin or equivalent 
- [colima](https://github.com/abiosoft/colima) for MacOS users
- python3
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
./generate_cluster.sh
```
```shell
tilt up --port 10351
```

# Issues

Cluster gets status 'provisioned', but the machine does not come up
```shell
❯ kubectl get clusters
NAME              PHASE         AGE     VERSION
talos-alloy-102   Provisioned   3m26s
❯ kubectl get machines
NAME                                            CLUSTER           NODENAME   PROVIDERID   PHASE     AGE     VERSION
talos-alloy-102-worker-56ffdb7c4bxgs6ld-bzq4j   talos-alloy-102                           Pending   4m41s   v1.26.1
```

failed to retrieve kubeconfig secret for Cluster
```shell
E0320 11:52:20.087321      12 packetmachine_controller.go:198]  "msg"="owning cluster is not found, skipping mapping." "error"=null "Namespace"="default" "PacketCluster"="talos-alloy-102" 
I0320 11:52:20.087463      12 packetcluster_controller.go:74] controller/packetcluster "msg"="Cluster Controller has not yet set OwnerRef" "name"="talos-alloy-102" "namespace"="default" "reconciler group"="infrastructure.cluster.x-k8s.io" "reconciler kind"="PacketCluster" 
I0320 11:52:20.111666      12 logr.go:249] packetmachinetemplate-resource "msg"="default"  "name"="talos-alloy-102-control-plane"
I0320 11:52:20.115060      12 logr.go:249] packetmachinetemplate-resource "msg"="validate create"  "name"="talos-alloy-102-control-plane"
I0320 11:52:20.122371      12 logr.go:249] packetmachinetemplate-resource "msg"="default"  "name"="talos-alloy-102-worker"
I0320 11:52:20.124017      12 logr.go:249] packetmachinetemplate-resource "msg"="validate create"  "name"="talos-alloy-102-worker"
I0320 11:52:20.167297      12 logr.go:249] packetmachinetemplate-resource "msg"="default"  "name"="talos-alloy-102-worker"
I0320 11:52:20.169172      12 logr.go:249] packetmachinetemplate-resource "msg"="validate update"  "name"="talos-alloy-102-worker"
I0320 11:52:20.188985      12 logr.go:249] packetcluster-resource "msg"="default"  "name"="talos-alloy-102"
I0320 11:52:20.190906      12 logr.go:249] packetcluster-resource "msg"="validate update"  "name"="talos-alloy-102"
E0320 11:52:20.195688      12 packetmachine_controller.go:198]  "msg"="owning cluster is not found, skipping mapping." "error"=null "Namespace"="default" "PacketCluster"="talos-alloy-102" 
I0320 11:52:20.196168      12 packetcluster_controller.go:112] controller/packetcluster "msg"="Reconciling PacketCluster" "cluster"="talos-alloy-102" "name"="talos-alloy-102" "namespace"="default" "reconciler group"="infrastructure.cluster.x-k8s.io" "reconciler kind"="PacketCluster" 
I0320 11:52:20.242756      12 logr.go:249] packetmachine-resource "msg"="default"  "name"="talos-alloy-102-worker-rgpmb"
I0320 11:52:20.246182      12 logr.go:249] packetmachine-resource "msg"="validate create"  "name"="talos-alloy-102-worker-rgpmb"
I0320 11:52:20.248594      12 packetmachine_controller.go:91] controller/packetmachine "msg"="Machine Controller has not yet set OwnerRef" "name"="talos-alloy-102-worker-rgpmb" "namespace"="default" "reconciler group"="infrastructure.cluster.x-k8s.io" "reconciler kind"="PacketMachine" 
I0320 11:52:20.290569      12 logr.go:249] packetmachine-resource "msg"="default"  "name"="talos-alloy-102-worker-rgpmb"
I0320 11:52:20.292249      12 packetmachine_controller.go:91] controller/packetmachine "msg"="Machine Controller has not yet set OwnerRef" "name"="talos-alloy-102-worker-rgpmb" "namespace"="default" "reconciler group"="infrastructure.cluster.x-k8s.io" "reconciler kind"="PacketMachine" 
I0320 11:52:20.292282      12 packetmachine_controller.go:91] controller/packetmachine "msg"="Machine Controller has not yet set OwnerRef" "name"="talos-alloy-102-worker-rgpmb" "namespace"="default" "reconciler group"="infrastructure.cluster.x-k8s.io" "reconciler kind"="PacketMachine" 
I0320 11:52:20.299365      12 logr.go:249] packetmachine-resource "msg"="default"  "name"="talos-alloy-102-worker-rgpmb"
I0320 11:52:20.309778      12 logr.go:249] packetmachine-resource "msg"="default"  "name"="talos-alloy-102-worker-rgpmb"
I0320 11:52:20.361878      12 logr.go:249] packetmachine-resource "msg"="default"  "name"="talos-alloy-102-worker-rgpmb"
E0320 11:52:20.395900      12 controller.go:317] controller/packetmachine "msg"="Reconciler error" "error"="failed to create scope: failed to get workload cluster client: failed to retrieve kubeconfig secret for Cluster default/talos-alloy-102: Secret \"talos-alloy-102-kubeconfig\" not found" "name"="talos-alloy-102-worker-rgpmb" "namespace"="default" "reconciler group"="infrastructure.cluster.x-k8s.io" "reconciler kind"="PacketMachine" 
E0320 11:52:20.395975      12 controller.go:317] controller/packetmachine "msg"="Reconciler error" "error"="failed to create scope: failed to get workload cluster client: failed to retrieve kubeconfig secret for Cluster default/talos-alloy-102: Secret \"talos-alloy-102-kubeconfig\" not found" "name"="talos-alloy-102-worker-rgpmb" "namespace"="default" "reconciler group"="infrastructure.cluster.x-k8s.io" "reconciler kind"="PacketMachine" 
```