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