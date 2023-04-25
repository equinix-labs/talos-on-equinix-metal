# Talos on Equinix Metal with Cluster API

Following project in an attempt to formulate the best practices for running
[Talos Linux](https://www.talos.dev/) on [Equinix Metal](https://deploy.equinix.com/metal/),
via [Kubernetes Cluster API](https://cluster-api.sigs.k8s.io/).

We will consider a basic model of 3 clusters. One management cluster, dedicated to Cluster API and other administrative 
tools. Two workload clusters deployed in different geographical locations. Workload clusters will advertise a
[Global Anycast IP Address](https://deploy.equinix.com/developers/docs/metal/networking/global-anycast-ips/) as their
Ingress Controller Load Balancer. This will allow us to operate a little bit like [cloudflare](https://blog.cloudflare.com/cloudflare-servers-dont-own-ips-anymore/)

We will have encrypted traffic between the nodes, thanks to [KubeSpan](https://www.talos.dev/v1.4/kubernetes-guides/network/kubespan/),
as well as Pod2Pod communication across clusters thanks to [cilium Cluster Mesh](https://docs.cilium.io/en/stable/network/clustermesh/clustermesh/)

```mermaid
graph LR    
    subgraph "ManagementCluster"
        subgraph "MCHardware"
            subgraph "MCmasters"
            MCm1(Master1)
            MCm2(Master2)
            MCm3(Master3)
            end
            subgraph "MCnodes"            
                MCn1(Node1)
                MCn2(Node2)
                MCn3(Node3)
            end
        end
        subgraph "MCapps"
            MC_CP_Endpoint(Control plane endpoint)
            MCIngress(ingress)
            MC_VPN(VPN)
            MC_ClusterAPI(Cluster API)
        end
    end
    subgraph "Workload"
        subgraph "WorkloadClusterA"
        subgraph "WCAHrdware"
            subgraph "WCAnodes"            
                WCAn1(Node1)
                WCAn2(Node2)
                WCAn3(Node3)
            end
            subgraph "WCAMasters"
                WCAm1(Master1)
                WCAm2(Master2)
                WCAm3(Master3)
            end
        end
        subgraph "WCAapps"
                WCA_CP_Endpoint(Control plane endpoint)
                WCAIngress(ingress)
                WCA_VPN(VPN)
        end       
    end
    subgraph "WorkloadClusterB"
        subgraph "WCBHardware"
            subgraph "WCBMasters"
                WCBm1(Master1)
                WCBm2(Master2)
                WCBm3(Master3)
            end
            subgraph "WCBnodes"            
                WCBn1(Node1)
                WCBn2(Node2)
                WCBn3(Node3)
            end
        end
        subgraph "WCBapps"
            WCB_CP_Endpoint(Control plane endpoint)
            WCBIngress(ingress)
            WCB_VPN(VPN)
        end        
    end
    end    

    MC_VPN(VPN) <--> WCB_VPN(VPN)
    MC_VPN(VPN) <--> WCA_VPN(VPN)

    admin([admin])-. MetalLB-managed <br> load balancer .->MCIngress[Ingress];
    admin([admin])-. CPEM-managed <br> load balancer .->MC_CP_Endpoint[Control plane endpoint];
    admin([admin])-. CPEM-managed <br> load balancer .->WCA_CP_Endpoint[Control plane endpoint];
    admin([admin])-. CPEM-managed <br> load balancer .->WCB_CP_Endpoint[Control plane endpoint];

    client1([client])-. MetalLB-managed <br> load balancer <br> anycast .->WCAIngress[Ingress];
    client1([client])-. MetalLB-managed <br> load balancer <br> anycast .->WCBIngress[Ingress];

    client2([client])-. MetalLB-managed <br> load balancer <br> anycast .->WCAIngress[Ingress];
    client2([client])-. MetalLB-managed <br> load balancer <br> anycast .->WCBIngress[Ingress];


```

- [quick setup](#quick-setup)
- [development setup](#developer-setup)
- [benchmark](#benchmark)
- [static config](#static-config)
- [todo](#todo)

## quick setup
### prerequisites

- Account on [Equinix Metal](https://deploy.equinix.com/metal/)
- Account on [GCP](https://cloud.google.com/gcp) together with access to domain managed by GCP
- [zsh env](https://github.com/ohmyzsh/ohmyzsh/tree/master/plugins/dotenv) plugin or equivalent
- MacOS users should consider [colima](https://github.com/abiosoft/colima) 
- [kconf](https://github.com/particledecay/kconf)
- [kind](https://kind.sigs.k8s.io/)
- [kubectl](https://kubernetes.io/docs/tasks/tools/)
- [clusterctl](https://cluster-api.sigs.k8s.io/clusterctl/overview.html)
- [Metal CLI](https://github.com/equinix/metal-cli/#installation)
- [talosctl](https://github.com/siderolabs/talos)
- about 60 min of your time


### setup
- Create a python [virtual environment](https://docs.python.org/3/library/venv.html) 
  ```shell
  python -m venv
  ```
  With [dotenv](https://github.com/ohmyzsh/ohmyzsh/tree/master/plugins/dotenv) the python venv should be automatically activated.  
  Install python resources:
  ```shell
  pip install -r resources.txt
  ```
- Examine and adjust [.env](.env). Create `secrets/secrets` and populate with required `ENV`
- Setup uses [invoke](https://www.pyinvoke.org/) to automate most of the actions needed to boot our model. Consider listing available tasks.
  ```shell
  invoke --list
  ```
  If you never worked with `invoke`, this library is kind of like `make`. It allows one to invoke shell commands and 
  at the same time conveniently(with python) convert different data structures(files)  
- Create a temporary local cluster. Setup uses [kind](https://kind.sigs.k8s.io/), If you are running on Mac, make sure to use
  [colima](https://github.com/abiosoft/colima). At the time of writing, this setup did not work on Docker Desktop.
  In the context of the `kind` cluster mix [CABPT](https://github.com/siderolabs/cluster-api-bootstrap-provider-talos), [CACPPT](https://github.com/siderolabs/cluster-api-control-plane-provider-talos), [CAPP](https://github.com/kubernetes-sigs/cluster-api-provider-packet):
  ```sh
  invoke cluster.kind-clusterctl-init
  ```
- Register VIPs to be used
  - by Talos as the control plane endpoint.
  - by the Ingress Controller LoadBalancer
  - by the Cluster Mesh API server LoadBalancer  

  Generate CAPI cluster manifest from template
  ```shell
  invoke cluster.build-manifests
  ```
  `cluster.build-manifests` task, by default, reads its config from [invoke.yaml](invoke.yaml). Produces a bunch of files
  in the `screts` directory. Take some time to check out those files. 
- Apply the cluster manifest  
  ```sh
  kubectl apply -f "secrets/${CLUSTER_NAME}.static-config.yaml"
  ```
- Wait for the cluster to come up
  ```shell
  watch clusterctl describe cluster "${CLUSTER_NAME}"
  ```
- Get the kubeconfig of the newly created cluster tin interact with the cluster
  ```sh
  invoke get-cluster-secrets
  ```
- One can use [kconf](https://github.com/particledecay/kconf) to merge the kubeconfig
  ```sh
  kconf add "secrets/${CLUSTER_NAME}.kubeconfig"
  ```
  In that case context can be easily set with
  ```shell
  kconf use admin@${CLUSTER_NAME}
  ```
- Patch cluster nodes with static routes to enable BGP, Install networking services (Cilium)
  ```shell
  invoke install-network-services
  ```
## developer setup
### developer prerequisites
On top of [user prerequisites](#user-prerequisites)
- [tilt](https://tilt.dev/)

### setup
- Make sure you have all the submodules
- Create the tilt-settings.json file in the cluster-api folder.
  ```sh
  touch cluster-api/tilt-settings.json 
  ```
- Copy the following into that file, updating the <> sections with relevant info:
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
- Create a temporary kind cluster, with cluster-api. Navigate to the cluster-api directory
  ```sh
  make tilt-up
  ```
- In another terminal continue with [user setup](#user-setup). This project uses [invoke](https://www.pyinvoke.org/) for automation.
  Use `invoke --list` to list all available tasks. Apart from other tasks invoke, ensures that the 
  configuration used in [benchmark](#benchmark) is the same as in case of [user setup](#user-setup) and [development setup](#developer-setup).
  - For additional instructions consider:
    - [Cluster Management API provider for Packet](https://github.com/kubernetes-sigs/cluster-api-provider-packet)
    - [Kubernetes Cloud Provider for Equinix Metal](https://github.com/equinix/cloud-provider-equinix-metal)
    - [Collection of templates for CAPI + Talos](https://github.com/siderolabs/cluster-api-templates) 
    - [Control plane provider for CAPI + Talos](https://github.com/siderolabs/cluster-api-control-plane-provider-talos)
    - [Cluster-api bootstrap provider for deploying Talos clusters.](https://github.com/siderolabs/cluster-api-bootstrap-provider-talos)

## benchmark
Using [talosctl](https://github.com/siderolabs/talos) and [Metal CLI](https://github.com/equinix/metal-cli/#installation) as described in the [official guide](https://www.talos.dev/v1.3/talos-guides/install/bare-metal-platforms/equinix-metal/).
With Talos control plane and worker configuration the same as in case of CAPI deployment.
- Register a VIP to be used by Talos as the control plane endpoint. This is a workaround for the current issue with
  CPEM EIP management. Generate cluster manifest with:
  ```shell
  invoke build_manifests
  ```
- Create the control plane node
  ```shell
  metal device create \
    --project-id $PROJECT_ID \
    --facility $FACILITY \
    --operating-system "talos_v1" \
    --plan $PLAN\
    --hostname toem-test-cp-1\
    --userdata-file secrets/controlplane-capi.yaml
  ```
- Create the worker node
  ```shell
  metal device create \
    --project-id $PROJECT_ID \
    --facility $FACILITY \
    --operating-system "talos_v1" \
    --plan $PLAN\
    --hostname toem-test-wo-1\
    --userdata-file secrets/worker-capi.yaml
  ```
- Observe the nodes coming up
  ```shell
  watch metal device get
  ```
- Get the device list
  ```shell
  metal device get -o yaml > secrets/device-list.yaml
  ```
- Find the control plane node IP address
  ```shell
  export config_plane_ip=$(yq '.[] | select(.hostname == "toem-test-cp-1") | .ip_addresses[] | select(.public == true and .address_family == 4) | .address' secrets/device-list.yaml | head -n 1)
  ```
- Configure talosctl
  ```shell
  talosctl --talosconfig secrets/talosconfig config endpoint ${config_plane_ip}
  talosctl --talosconfig secrets/talosconfig config node ${config_plane_ip}
  talosctl --talosconfig secrets/talosconfig bootstrap
  talosctl --talosconfig secrets/talosconfig kubeconfig secrets/kubeconfig
  ```
- Use kubeconfig from secrets/kubeconfig to interact with the cluster
  ```shell
  kconf add secrets/kubeconfig
  kconf use admin@${CLUSTER_NAME}
  ```
- `kubectl` to hearts content...

## ToDo
- Control Plane endpoint load balancing [\[1\]](https://github.com/KrystianMarek/talos-on-equinix-metal/issues/5)