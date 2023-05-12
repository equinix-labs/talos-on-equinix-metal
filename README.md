# GOCY
**Open Source, Globally distributed, scalable, secure and performant Cloud Native Developer Platform for Startups and Enterprises on Equinix Metal**

Following project in an attempt to run
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

- [Quick setup](#quick-setup)
  - [prerequisites](#prerequisites)
  - [environment](#environment)
  - [local cluster](#local-cluster)
  - [barycenter](#barycenter)
  - [satellites](#satellites)
  - [fun part](#messing-around-with-cluster-mesh)
- [Development setup](#developer-setup)

## Quick setup

We will consider a simple model, consisting of 3 clusters as described above. Configuration input for the model is
located in [jupiter.constellation.yaml](templates/jupiter.constellation.yaml).
In this document and code, I will refer to the model as `constellation`. Consisting
of the management cluster named `jupiter` - the [barycenter](https://en.wikipedia.org/wiki/Barycenter)
Together with two satellites - workload clusters: `ganymede` and `callisto`.

### prerequisites

- Account on [Equinix Metal](https://deploy.equinix.com/metal/)
- Account on [GCP](https://cloud.google.com/gcp) together with access to domain managed by GCP  
  ( Feel free to open a PR extending support to other providers like AWS.)
- Account on https://hub.docker.com
- [zsh env](https://github.com/ohmyzsh/ohmyzsh/tree/master/plugins/dotenv) plugin or equivalent
- MacOS users should consider [colima](https://github.com/abiosoft/colima)
- [kconf](https://github.com/particledecay/kconf)
- [kind](https://kind.sigs.k8s.io/)
- [kubectl](https://kubernetes.io/docs/tasks/tools/)
- [clusterctl](https://cluster-api.sigs.k8s.io/clusterctl/overview.html)
- [Metal CLI](https://github.com/equinix/metal-cli/#installation)
- [talosctl](https://github.com/siderolabs/talos)
- about 60 min of your time and about $50 USD ( domain + Equinix Metal )

### environment

- Once you clone this repository, `cd` into it and create a python
  [virtual environment](https://docs.python.org/3/library/venv.html)
  ```shell
  python -m venv
  ```
  With [dotenv](https://github.com/ohmyzsh/ohmyzsh/tree/master/plugins/dotenv)
  the python venv should be automatically activated.  
  Install python resources:
  ```shell
  pip install -r resources.txt
  ```
- Setup uses [invoke](https://www.pyinvoke.org/) to automate most of the actions needed to boot our constellation.
  Consider listing available tasks first to make sure everything is ready.
  ```shell
  invoke --list
  ```
  If you never worked with `invoke`, this library is kind of like `make`. It allows one to invoke shell commands and
  at the same time conveniently(with python) convert different data structures(files)  
  Most of the shell commands are echoed into the console, so that you can see what is happening behind the scene.
- Examine [secrets.yaml](templates/secrets.yaml) and [jupiter.constellation.yaml](templates/jupiter.constellation.yaml)  
  run
  ```shell
  invoke gocy.init
  ```
  to set up your configuration directory - `${HOME}/.gocy`. The `gocy.init` task will copy the `secrets.yaml`  
  file template over there. Populate it with required data. This is also the place where you store the constellation spec
  files. You can have more spec files. For now while naming them remember to match `[name].constellation.yaml` with
  `.name` value in the same file.
- If you decide to create your own constellation spec file(s), you can make sure they are correctly parsed by the tool
  by running
  ```shell
  invoke gocy.list-constellations
  ```
  You can adjust the constellation context by running
  ```shell
  invoke gocy.ccontext-set [constellation_name]
  ```
### local cluster

- Setup uses [kind](https://kind.sigs.k8s.io/), If you are running on Mac, make sure to use
  [colima](https://github.com/abiosoft/colima). At the time of writing, this setup did not work on Docker Desktop.
  This task will create a temporary local cluster k8s. It will provision it with  
  [CAPI](https://cluster-api.sigs.k8s.io/) and other providers:
  [CABPT](https://github.com/siderolabs/cluster-api-bootstrap-provider-talos),
  [CACPPT](https://github.com/siderolabs/cluster-api-control-plane-provider-talos),
  [CAPP](https://github.com/kubernetes-sigs/cluster-api-provider-packet)
  ```sh
  invoke cluster.kind-clusterctl-init
  ```
- Next, we will bundle few tasks together:
  - Register VIPs to be used
    - by Talos as the control plane endpoint.
    - by the Ingress Controller LoadBalancer
    - by the Cluster Mesh API server LoadBalancer
  - Generate CAPI cluster manifest from template

  `cluster.build-manifests` task, by default, reads its config from [invoke.yaml](invoke.yaml). Produces a bunch of files
  in the `screts` directory. Take some time to check out those files.
  ```shell
  invoke cluster.build-manifests
  ``` 
### barycenter
- We are ready to boot our first cluster. It will become our new management cluster. Once it is ready
  we will transfer CAPI state from the local kind cluster onto it. Apply the cluster manifest
  ```sh
  kubectl apply -f ${HOME}/.gocy/jupiter/jupiter/cluster-manifest.static-config.yaml
  ```
- Wait for the cluster to come up, there are several ways you can observe the progress. Most reliable indicators are
  ```shell
  watch metal device get   
  ```
  ```shell
  kubectl get machinedeployments.cluster.x-k8s.io,taloscontrolplanes.controlplane.cluster.x-k8s.io
  ``` 
  Due to a bug `clusterctl` is not the best pick.
  ```shell
  watch clusterctl describe cluster jupiter
  ```
  Once `watch metal device get` shows state `active` next to our talos boxes, we can proceed.
- With the devices up, we are ready to pull the secrets. In this task we will pull both `kubeconfig` and `talosconfig`.  
  Also we will bootstrap the talos etcd.
  ```sh
  invoke cluster.get-cluster-secrets -c jupiter
  ```
  Once this is done we can add out new `kubeconfig`
  ```shell
  kconf add ${HOME}/.gocy/jupiter/jupiter/jupiter.kubeconfig
  ```
  then change context to `jupiter`
  ```shell
  kconf use admin@jupiter
  ```
  In the end we merge the `talosconfig`
  ```shell
  talosctl config merge ${HOME}/.gocy/jupiter/jupiter/talosconfig
  ```
- At this stage we should start some pods showing up on our cluster. You can `get pods` to verify that.
  ```shell
  kubectl get pods -A
  ```
  There won't be much going on. Maybe `coredns` that fails to change status to `Running`. This is OK, we do not have CNI
  yet.
- We will install our CNI (Cilium) together with MetalLB
  ```shell
  invoke network.install-network-service-dependencies
  ```
  Observe your pods and nodes
  ```shell
  kubectl get pods,nodes -A -o wide
  ```
  We want all pods in `Running` state and all nodes in `Ready` state. If any of the pods has issues becoming operational.
  You can give it a gentle `kubectl delete pod`. If any of the nodes is not in the `Ready` state, take a break.
- Will everything up and running we can proceed with setting up BGP. This step will path the cluster nodes with static
  routes so that MetalLB speakers can reach their BGP peers
  ```shell
  invoke network.install-network-service
  ```
  At this point the `clustermesh-apiserver` service should get its LoadBalancer IP address.
- Normally we would go straight to task `apps.install-dns-and-tls`, however this task expects a dedicated ServiceAccount
  to be present in GCP, used for DNS management. Take a look at the methods `deploy_dns_management_token`
  and `deploy_dns_management_token`. If you have access to the GCP console and a domain managed by it,
  you can create an account like that. By following [instructions](https://cert-manager.io/v1.6-docs/configuration/acme/dns01/google/).
  Once you have the account run
  ```shell
  invoke apps.deploy-dns-management-token
  ```
  and verify that a file `secrets/dns_admin_token.json` is present.
- Assuming all went well you can proceed with
  ```shell
  invoke apps.install-dns-and-tls
  ```
  to deploy external-dns and cert-manager.
  Then
  ```shell
  invoke apps.install-ingress-controller
  ```
  to deploy nginx ingress controller.  
  Observe your pods, they all should be in the `Running` status
  ```shell
  kubectl get pods -A
  ```
- At this state we are almost ready with `jupiter`. Switch k8s context back to kind cluster with
  ```shell
  invoke cluster.use-kind-cluster-context
  ```
  or
  ```shell
  kconf use kind-toem-capi-local
  ```
  Make sure that `machinedeployments` and `taloscontrolplanes` are `ready`
  ```shell
  kubectl get machinedeployments.cluster.x-k8s.io,taloscontrolplanes.controlplane.cluster.x-k8s.io
  ```
  The output should look similiar to this
  ```shell
  NAME                                                 CLUSTER    REPLICAS   READY   UPDATED   UNAVAILABLE   PHASE     AGE   VERSION
  machinedeployment.cluster.x-k8s.io/jupiter-worker    jupiter    2          2       2         0             Running   16h   v1.27.1
  
  NAME                                                                     READY   INITIALIZED   REPLICAS   READY REPLICAS   UNAVAILABLE REPLICAS
  taloscontrolplane.controlplane.cluster.x-k8s.io/jupiter-control-plane    true    true          1          1
  ```
- If this is the case you can move the CAPI state from the local kind cluster to `jupiter`.
  ```shell
  invoke cluster.clusterctl-move
  ```
  Switch context to `jupiter`
  ```shell
  kconf use admin@jupiter
  ```
  and verify
  ```shell
  kubectl get clusters 
  ```
  Output should be similar to
  ```shell
  NAME       PHASE         AGE   VERSION
  jupiter    Provisioned   16h
  ```
- As an optional step we can enable [KubeSpan](https://www.talos.dev/v1.3/kubernetes-guides/network/kubespan/) with
  ```shell
  invoke network.apply-kubespan-patch
  ```
  and verify with
  ```shell
  talosctl get kubespanpeerstatus
  ```

### satellites

If you made it this far, and everything works, **congratulations !!!**  
We have the management cluster in place, but in order to complete the constellation we need to deploy
`ganymede` and `callisto`.  
This should be easier this time, because the flow is mostly the same as in the case of management cluster.
At this state it is a good idea to open another terminal and with each cluster complete open a tab with  
`k9s --context admin@CONSTELLATION_MEMBER`.
- Pick the one satellite you would like to go first and stick to it. Once the process is complete repeat it for remaining
  cluster.
  ```shell
  export MY_SATELLITE="ganymede"
  ``` 
- Apply cluster manifest
  ```sh
  kubectl apply -f ${HOME}/.gocy/jupiter/${MY_SATELLITE}/cluster-manifest.static-config.yaml
  ```
- Wait for it to come up
  ```shell
  watch metal device get   
  ```
- Get secrets
  ```sh
  invoke cluster.get-cluster-secrets -c ${MY_SATELLITE}
  ```
  add `kubeconfig`
  ```shell
  kconf add ${HOME}/.gocy/jupiter/${MY_SATELLITE}/${MY_SATELLITE}.kubeconfig
  ```
  change context to `${MY_SATELLITE}`
  ```shell
  kconf use admin@${MY_SATELLITE}
  ```
  merge the `talosconfig`
  ```shell
  talosctl config merge ${HOME}/.gocy/jupiter/${MY_SATELLITE}/talosconfig
  ```
- Install Cilium & MetalLB
  ```shell
  invoke network.install-network-service-dependencies
  ```
- Make sure pods and nodes are ready
  ```shell
  kubectl get pods,nodes -A -o wide
  ```
  Make sure that `machinedeployments` and `taloscontrolplanes` are `ready`
  ```shell
  kubectl get machinedeployments.cluster.x-k8s.io,taloscontrolplanes.controlplane.cluster.x-k8s.io
  ```
  If not, take a break.
- Enable BGP
  ```shell
  invoke network.install-network-service
  ```
- At this point you should already have your token for GCP DNS administration. You can go straight to
  ```shell
  invoke apps.install-dns-and-tls
  ```
- Install ingress controller
  ```shell
  invoke apps.install-ingress-controller
  ```
- Make sure pods are running
  ```shell
  kubectl get pods -A -o wide
  ```
  and ingress controller has a LoadBalancer with public IP attached
  ```shell
  kubectl get services -n ingress-bundle ingress-bundle-ingress-nginx-controller
  ```
  This IP address should be the same in all satellite clusters ([Anycast](https://en.wikipedia.org/wiki/Anycast)).
- If everything is OK proceed with demo app
  ```shell
  invoke apps.install-whoami-app
  ```
  Wait for certificate to become ready. It can take up to few minutes.
  ```shell
  watch kubectl get certificates -A
  ```
  If it takes too long ~>5min check logs of `dns-and-tls-dependencies-cert-manager`. It might happen that the secret you
  set up for your DNS provider is incorrect.
- Assuming it all worked, at this stage you should be able to get a meaningful response from
  ```shell
  curl -L "whoami.${TOEM_TEST_SUBDOMAIN}.${GCP_DOMAIN}"
  ```
- Complete the setup by enabling KubeSpan
  ```shell
  invoke network.apply-kubespan-patch
  ```
- Go to [satellites](#satellites) and repeat the process for remaining members.

### messing around with cluster mesh

- Switch context to bary node
  ```shell
  kconf use admin@jupiter
  ```
  You should be getting something like:
  ```shell
  ❯ kubectl get clusters
  NAME       PHASE         AGE   VERSION
  callisto   Provisioned   17h
  ganymede   Provisioned   22h
  jupiter    Provisioned   17h
  ```
  ```shell
  ❯ kubectl get machinedeployments.cluster.x-k8s.io,taloscontrolplanes.controlplane.cluster.x-k8s.io
  NAME                                                 CLUSTER    REPLICAS   READY   UPDATED   UNAVAILABLE   PHASE     AGE   VERSION
  machinedeployment.cluster.x-k8s.io/callisto-worker   callisto   2          2       2         0             Running   17h   v1.27.1
  machinedeployment.cluster.x-k8s.io/ganymede-worker   ganymede   2          2       2         0             Running   22h   v1.27.1
  machinedeployment.cluster.x-k8s.io/jupiter-worker    jupiter    2          2       2         0             Running   17h   v1.27.1
  
  NAME                                                                     READY   INITIALIZED   REPLICAS   READY REPLICAS   UNAVAILABLE REPLICAS
  taloscontrolplane.controlplane.cluster.x-k8s.io/callisto-control-plane   true    true          1          1
  taloscontrolplane.controlplane.cluster.x-k8s.io/ganymede-control-plane   true    true          1          1
  taloscontrolplane.controlplane.cluster.x-k8s.io/jupiter-control-plane    true    true          1          1
  ```
- If this is the case enable Cluster Mesh
  ```shell
  invoke network.enable-cluster-mesh
  ```
  Once complete you should get
  ```shell
  ❯ cilium --namespace network-services clustermesh status
  ✅ Cluster access information is available:
  - [REDACTED]:2379
  ✅ Service "clustermesh-apiserver" of type "LoadBalancer" found
  ✅ All 3 nodes are connected to all clusters [min:2 / avg:2.0 / max:2]
  🔌 Cluster Connections:
  - ganymede: 3/3 configured, 3/3 connected
  - callisto: 3/3 configured, 3/3 connected
  🔀 Global services: [ min:14 / avg:14.0 / max:14 ]
  ```
- Now you can play with Cilium [Load-balancing & Service Discovery](https://docs.cilium.io/en/stable/network/clustermesh/services/)
- And with already present `whoami` app.  
  Grap the name of a running debug pod
  ```shell
  kubectl get pods -n network-services | grep debug
  ```
  ```shell
  kubectl --context admin@ganymede --namespace network-services exec [DEBUG_POD_NAME] -- bash -c 'curl -sL whoami-service.test-application'
  ```
  You should be getting responses randomly from `ganymede` and `callisto`
## developer setup

Consider this only if you need to dig deep into how individual providers work.

### prerequisites
On top of [user prerequisites](#prerequisites)
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
- In another terminal continue with [user setup](#setup).
  Use `invoke --list` to list all available tasks. Apart from other tasks invoke, ensures that the
  - For additional instructions consider:
    - [Cluster Management API provider for Packet](https://github.com/kubernetes-sigs/cluster-api-provider-packet)
    - [Kubernetes Cloud Provider for Equinix Metal](https://github.com/equinix/cloud-provider-equinix-metal)
    - [Collection of templates for CAPI + Talos](https://github.com/siderolabs/cluster-api-templates)
    - [Control plane provider for CAPI + Talos](https://github.com/siderolabs/cluster-api-control-plane-provider-talos)
    - [Cluster-api bootstrap provider for deploying Talos clusters.](https://github.com/siderolabs/cluster-api-bootstrap-provider-talos)
