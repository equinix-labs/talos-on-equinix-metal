open shell
```shell
kubectl exec --stdin --tty debug -- /bin/bash
```

restart cilium components
```shell
kubectl -n network-services rollout restart deployment/cilium-operator
kubectl -n network-services rollout restart ds/cilium
cilium -n network-services connectivity test
```

patch talos machine running config
```shell
talosctl patch mc -p @kubespan.yaml
```

https://www.talos.dev/v1.4/kubernetes-guides/network/kubespan/#enabling-for-an-existing-cluster
```shell
talosctl get kubespanpeerstatus
```
```shell
talosctl config remove -y ganymede
```

```shell
cilium --context admin@callisto --namespace network-services clustermesh status
```
```shell
cilium --context admin@jupiter --namespace network-services hubble ui --port-forward 12000
cilium --context admin@ganymede --namespace network-services hubble ui --port-forward 12001
cilium --context admin@callisto --namespace network-services hubble ui --port-forward 12002
```

```shell
k9s --context admin@jupiter
k9s --context admin@callisto
k9s --context admin@ganymede
```

```shell
kubectl --context admin@ganymede --namespace network-services exec debug-mtzhv -- bash -c 'curl -L whoami.v4...'
kubectl --context admin@ganymede --namespace network-services exec debug-mtzhv -- bash -c 'curl -sL whoami-service.test-application'
```

```shell
kubectl get machinedeployments.cluster.x-k8s.io,taloscontrolplanes.controlplane.cluster.x-k8s.io
```