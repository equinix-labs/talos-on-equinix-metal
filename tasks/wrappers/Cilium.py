import base64
import logging
from typing import Union

import yaml
from invoke import Context, Failure

from tasks.controllers.MetalCtrl import MetalCtrl
from tasks.dao.ProjectPaths import ProjectPaths, RepoPaths
from tasks.dao.SystemContext import SystemContext
from tasks.helpers import get_fqdn, str_presenter
from tasks.models.ConstellationSpecV01 import Cluster, VipRole
from tasks.models.Namespaces import Namespace
from tasks.wrappers.JinjaWrapper import JinjaWrapper

yaml.add_representer(str, str_presenter)
yaml.representer.SafeRepresenter.add_representer(str, str_presenter)  # to use with safe_dump


class Cilium:
    _state: SystemContext
    _cluster: Cluster
    _ctx: Context
    _echo: bool

    def __init__(self, ctx: Context, state: SystemContext, echo: bool):
        self._state = state
        self._ctx = ctx
        self._echo = echo

    def status(self, namespace: Namespace = Namespace.network_services):
        for cluster in self._state.constellation:
            self._ctx.run("cilium --context admin@{} --namespace {} status".format(
                cluster.name,
                namespace
            ), echo=self._echo)

    def cluster_mesh_status(self, namespace: Namespace = Namespace.network_services):
        for cluster in self._state.constellation:
            self._ctx.run("cilium --context admin@{} --namespace {} clustermesh status".format(
                cluster.name,
                namespace
            ), echo=self._echo)

    def _get_mesh_client_certs(self, namespace: Namespace = Namespace.network_services):
        client_certificates = dict()
        for cluster in self._state.constellation:
            client_cert_yaml = self._ctx.run(
                "kubectl --namespace {} get secret clustermesh-apiserver-client-cert -o yaml".format(
                    namespace
                ), hide="stdout", echo=self._echo).stdout
            client_cert = dict(yaml.safe_load(client_cert_yaml))

            client_certificates[cluster.name] = dict()
            client_certificates[cluster.name]["{}.etcd-client-ca.crt".format(cluster.name)] = client_cert['data']['ca.crt']
            client_certificates[cluster.name]["{}.etcd-client.crt".format(cluster.name)] = client_cert['data']['tls.crt']
            client_certificates[cluster.name]["{}.etcd-client.key".format(cluster.name)] = client_cert['data']['tls.key']

        return client_certificates

    def _patch_cilium_clustermesh_secret(self, cluster_mesh_certs: dict,
                                         namespace: Namespace = Namespace.network_services):
        """
        'cilium clustermesh connect' uses remote certificate to make the connect, contrary to:
        https://medium.com/codex/establish-cilium-clustermesh-whelm-chart-11b08b0c995c
        'cilium clustermesh connect' creates host aliases for apiserver LB under *.cilium.io,
        patches cilium daemonset with it.
        """
        for cluster in self._state.constellation:
            cluster_mesh_config_yaml = self._ctx.run(
                "kubectl --context admin@{} -n {} get secret cilium-clustermesh -o yaml".format(
                    cluster.name,
                    namespace,
                ), hide="stdout", echo=self._echo).stdout
            cluster_mesh_config = dict(yaml.safe_load(cluster_mesh_config_yaml))

            del (cluster_mesh_config['metadata']['creationTimestamp'])
            del (cluster_mesh_config['metadata']['resourceVersion'])
            del (cluster_mesh_config['metadata']['uid'])

            cluster_mesh_config_data_keys = cluster_mesh_config['data'].keys()
            print("#" * 5 + " " + cluster.name + " =>")
            for key in cluster_mesh_config_data_keys:
                if key in self._state.constellation:  # Patch config
                    decoded_yaml = base64.b64decode(cluster_mesh_config['data'][key])
                    endpoint_config = dict(yaml.safe_load(decoded_yaml))
                    # print(cluster.name)
                    # print(endpoint_config)
                    metal_ctrl = MetalCtrl(self._state, self._echo, Cluster(name=key))
                    endpoint_config['endpoints'] = [
                        "https://{}:2379".format(
                            get_fqdn(['mesh', key], self._state.secrets, cluster)),
                        "https://{}:2379".format(
                            metal_ctrl.get_vips(VipRole.mesh).public_ipv4[0])
                        # "https://clustermesh-apiserver.{}.svc:2379".format(namespace)
                    ]

                    encoded_yaml = base64.b64encode(bytes(yaml.safe_dump(endpoint_config), 'utf-8')).decode('utf-8')
                    cluster_mesh_config['data'][key] = encoded_yaml
                    print("Patched config: {}".format(key))
                else:  # Patch certificates
                    for cluster_name in cluster_mesh_certs:
                        for cert_name in cluster_mesh_certs[cluster_name]:
                            if key == cert_name:
                                cluster_mesh_config['data'][key] = cluster_mesh_certs[cluster_name][cert_name]
                                print("Patched cert: {}".format(key))

            paths = ProjectPaths(constellation_name=self._state.constellation.name, cluster_name=cluster.name)
            with open(paths.patch_mesh_secret_file(), 'w') as cluster_mesh_secret_file:
                yaml.safe_dump(cluster_mesh_config, cluster_mesh_secret_file)

            self._ctx.run("kubectl --context admin@{} -n {} delete secret cilium-clustermesh".format(
                cluster.name,
                namespace
            ), echo=self._echo)

            self._ctx.run("kubectl --context admin@{} apply -f {}".format(
                cluster.name,
                paths.patch_mesh_secret_file()
            ), echo=self._echo)

            self.restart(namespace)

    def _cluster_mesh_connect(self, namespace: Namespace = Namespace.network_services):
        connected_targets = list()
        for cluster in self._state.constellation:
            for cluster_b in self._state.constellation:
                if cluster.name != cluster_b.name and Union[cluster.name, cluster_b.name] not in connected_targets:
                    # print("Connect {} => {}".format(cluster.name, cluster_b.name))
                    self._ctx.run(
                        "cilium --namespace {} --context {} clustermesh connect --destination-context {}".format(
                            namespace.value,
                            'admin@' + cluster.name,
                            'admin@' + cluster_b.name
                        ), echo=self._echo)
                    connected_targets.append(Union[cluster.name, cluster_b.name])

    def _deploy_kubeconfigs(self):
        """
        Allow constellation members to connect each others KubeAPI.
        This is to enable multi cluster CockroachDB (among others)
        https://faun.pub/connecting-multiple-kubernetes-clusters-on-vsphere-with-the-cilium-cluster-mesh-964f95267df4
        ToDo: generate dedicated, scope kubeconfig for this purpose.
        """
        for cluster in self._state.constellation:
            for cluster_b in self._state.constellation:
                if cluster.name != cluster_b.name:
                    paths = ProjectPaths(self._state.constellation.name, cluster_b.name)
                    try:
                        self._ctx.run(
                            "kubectl --context admin@{} --namespace {} create secret generic"
                            " {}.kubeconfig --from-file={}.kubeconfig={}".format(
                                cluster.name,
                                Namespace.kube_system,
                                cluster_b.name,
                                cluster_b.name,
                                paths.kubeconfig_file()
                            ))
                    except Failure:
                        logging.info("Secret already exists")

    def _patch_coredns_configmap(self):
        """
        Patch CoreDNS ConfigMap so that constellation members are aware of each other pods. Part of
        https://faun.pub/connecting-multiple-kubernetes-clusters-on-vsphere-with-the-cilium-cluster-mesh-964f95267df4
        https://www.cockroachlabs.com/docs/stable/orchestrate-cockroachdb-with-kubernetes-multi-cluster
        """
        jinja = JinjaWrapper()
        repo_paths = RepoPaths()

        for cluster in self._state.constellation:
            entries = []
            paths = ProjectPaths(self._state.constellation.name, cluster.name)

            for cluster_b in self._state.constellation:
                if cluster.name != cluster_b.name:

                    control_plane = MetalCtrl(self._state, self._echo, cluster_b).get_vips(VipRole.cp).public_ipv4[0]
                    data = {
                        'cluster_name': cluster_b.name,
                        'control_plane_endpoint': 'https://{}:6443'.format(control_plane)
                    }
                    entries.append(data)

            jinja.render(repo_paths.coredns_patch_file(), paths.coredns_patch_file(), {'entries': entries})
            with open(paths.coredns_patch_file()) as coredns_patch_file:
                coredns_patch = dict(yaml.safe_load(coredns_patch_file))

            configmap_yaml = self._ctx.run(
                'kubectl --context admin@{} --namespace {} get configmap coredns -o yaml'.format(
                    cluster.name,
                    Namespace.kube_system,
                ),
                hide='stdout', echo=self._echo).stdout
            configmap = dict(yaml.safe_load(configmap_yaml))

            if coredns_patch['data']['Corefile'] not in configmap['data']['Corefile']:
                core_file = configmap['data']['Corefile'].splitlines()
                core_file_patch = coredns_patch['data']['Corefile'].splitlines()
                core_file.extend(core_file_patch)
                configmap['data']['Corefile'] = "\n".join(core_file)
                del(configmap['metadata']['creationTimestamp'])
                del (configmap['metadata']['resourceVersion'])
                del (configmap['metadata']['uid'])

                with open(paths.coredns_configmap_file(), 'w') as coredns_configmap_file:
                    yaml.dump(dict(configmap), coredns_configmap_file)

                    self._ctx.run("kubectl --context admin@{} apply -f {}".format(
                        cluster.name,
                        paths.coredns_configmap_file()
                    ), echo=self._echo)

    def _patch_coredns_deployment(self):
        """
        With CoreDNS ConfigMap patched, we need to patch the deployment as well in order to mount the secret volume
        """
        jinja = JinjaWrapper()
        repo_paths = RepoPaths()

        for cluster in self._state.constellation:
            clusters = []
            paths = ProjectPaths(self._state.constellation.name, cluster.name)

            for cluster_b in self._state.constellation:
                if cluster.name != cluster_b.name:
                    clusters.append(cluster_b)

            jinja.render(
                repo_paths.coredns_deployment_patch_file(),
                paths.coredns_deployment_patch_file(), {'clusters': clusters})

            self._ctx.run("kubectl --context admin@{} --namespace {} patch deployment coredns "
                          "--type strategic --patch-file {}".format(
                            cluster.name,
                            Namespace.kube_system,
                            paths.coredns_deployment_patch_file()
                          ), echo=self._echo)

    def cluster_mesh_connect(self, namespace: Namespace = Namespace.network_services):
        self._cluster_mesh_connect(namespace)
        client_mesh_certs = self._get_mesh_client_certs(namespace)
        self._patch_cilium_clustermesh_secret(client_mesh_certs, namespace)
        self._deploy_kubeconfigs()
        self._patch_coredns_configmap()
        self._patch_coredns_deployment()

    def restart(self, namespace: Namespace = Namespace.network_services):
        for cluster in self._state.constellation:
            self._ctx.run("kubectl --context admin@{} --namespace {} rollout restart deployment/cilium-operator".format(
                cluster.name,
                namespace), echo=self._echo)

            self._ctx.run("kubectl --context admin@{} --namespace {} rollout restart deployment/clustermesh-apiserver".format(
                cluster.name,
                namespace), echo=self._echo)

            self._ctx.run("kubectl --context admin@{} --namespace {} rollout restart daemonset/cilium".format(
                cluster.name,
                namespace), echo=self._echo)

    def cluster_mesh_disconnect(self, namespace: Namespace = Namespace.network_services):
        for cluster in self._state.constellation:
            for cluster_b in self._state.constellation:
                if cluster.name != cluster_b.name:
                    self._ctx.run(
                        "cilium --context admin@{} --namespace {} clustermesh "
                        "disconnect --destination-context admin@{}".format(
                            cluster.name,
                            namespace,
                            cluster_b.name
                        ),
                        echo=self._echo)

        self.restart(namespace)