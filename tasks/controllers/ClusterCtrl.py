import logging
import os
import shutil

import yaml
from invoke import Failure

from tasks.controllers.ApplicationsCtrl import ApplicationsCtrl
from tasks.controllers.MetalCtrl import MetalCtrl
from tasks.dao.ProjectPaths import ProjectPaths, RepoPaths
from tasks.dao.SystemContext import SystemContext
from tasks.helpers import get_cpem_config_yaml, str_presenter, user_confirmed
from tasks.models.ConstellationSpecV01 import Cluster, Constellation, VipRole
from tasks.models.Defaults import KIND_CONTEXT_NAME
from tasks.models.Namespaces import Namespace
from tasks.wrappers.JinjaWrapper import JinjaWrapper

CONTROL_PLANE_NODE = 'control-plane'
WORKER_NODE = 'worker'


yaml.add_representer(str, str_presenter)
yaml.representer.SafeRepresenter.add_representer(str, str_presenter)  # to use with safe_dump


class ClusterCtrl:
    _state: SystemContext
    _constellation: Constellation
    _cluster: Cluster
    _paths: ProjectPaths
    _echo: bool

    def __init__(self, state: SystemContext, cluster: Cluster, echo: bool):
        self._state = state
        self._constellation = state.constellation
        self._cluster = cluster
        self._paths = ProjectPaths(state.constellation.name, cluster.name)
        self._echo = echo

    def patch_cluster_spec_network(self, cluster_manifest: list):
        """
        Patches cluster template with corrected dnsDomain,podSubnets,serviceSubnets
        Settings in Cluster.spec.clusterNetwork do not affect the running cluster.
        Those changes need to be put in the Talos config.
        """
        for resource in cluster_manifest:
            if resource['kind'] == 'TalosControlPlane':
                patches = resource['spec']['controlPlaneConfig']['controlplane']['configPatches']
                for patch in patches:
                    if patch['path'] == '/cluster/network':
                        patch['value']['dnsDomain'] = "{}.local".format(self._cluster.name)
                        patch['value']['podSubnets'] = self._cluster.pod_cidr_blocks
                        patch['value']['serviceSubnets'] = self._cluster.service_cidr_blocks
            if resource['kind'] == 'TalosConfigTemplate':
                patches = resource['spec']['template']['spec']['configPatches']
                for patch in patches:
                    if patch['path'] == '/cluster/network':
                        patch['value']['dnsDomain'] = "{}.local".format(self._cluster.name)
                        patch['value']['podSubnets'] = self._cluster.pod_cidr_blocks
                        patch['value']['serviceSubnets'] = self._cluster.service_cidr_blocks
            if resource['kind'] == 'Cluster':
                resource['spec']['clusterNetwork']['pods']['cidrBlocks'] = self._cluster.pod_cidr_blocks
                resource['spec']['clusterNetwork']['services']['cidrBlocks'] = self._cluster.service_cidr_blocks

        return cluster_manifest

    def talosctl_gen_config(self, ctx):
        """
        Produces initial Talos machine configuration, that later on will be patched with custom cluster settings.
        """
        equinix = MetalCtrl(self._state, self._echo, self._cluster)

        with ctx.cd(self._paths.talos_dir()):
            ctx.run(
                "talosctl gen config {} https://{}:6443".format(
                    self._cluster.name,
                    equinix.get_vips(VipRole.cp).public_ipv4[0]
                ),
                echo=self._echo
            )

    def build_capi_manifest(self, secrets, cluster_jinja_template, _md_yaml):
        metal_ctrl = MetalCtrl(self._state, self._echo, self._cluster)

        data = {
            'TOEM_CPEM_SECRET': get_cpem_config_yaml(),
            'TOEM_CP_ENDPOINT': metal_ctrl.get_vips(VipRole.cp).public_ipv4[0],
            'SERVICE_DOMAIN': "{}.local".format(self._cluster.name),
            'CLUSTER_NAME': self._cluster.name,
            'METRO': self._cluster.metro,
            'CONTROL_PLANE_NODE_TYPE': self._cluster.control_nodes[0].plan,
            'CONTROL_PLANE_MACHINE_COUNT': self._cluster.control_nodes[0].count,
            'TALOS_VERSION': self._cluster.talos,
            'CPEM_VERSION': self._cluster.cpem,
            'KUBERNETES_VERSION': self._cluster.kubernetes,
            'namespace': Namespace.argocd
        }
        data.update(secrets)

        jinja = JinjaWrapper().jinja
        cluster_yaml_tpl = jinja.from_string(cluster_jinja_template)
        cluster_yaml = cluster_yaml_tpl.render(data)

        for worker_node in self._cluster.worker_nodes:
            worker_yaml_tpl = jinja.from_string(_md_yaml)
            data['machine_name'] = "{}-machine-{}".format(
                self._cluster.name,
                worker_node.plan.replace('.', '-'))  # ToDo: CPEM blows up if there are dots in machine name
            data['WORKER_NODE_TYPE'] = worker_node.plan
            data['WORKER_MACHINE_COUNT'] = worker_node.count
            cluster_yaml = "{}\n{}".format(cluster_yaml, worker_yaml_tpl.render(data))

        cluster_manifest = list(yaml.safe_load_all(cluster_yaml))

        self.patch_cluster_spec_network(cluster_manifest)

        with open(self._paths.cluster_capi_manifest_file(), 'w') as cluster_template_file:
            yaml.dump_all(cluster_manifest, cluster_template_file)

    def talos_apply_config_patch(self, ctx):
        cluster_secrets_dir = self._paths.talos_dir()
        cluster_manifest_file_name = self._paths.cluster_capi_manifest_file()

        with open(cluster_manifest_file_name) as cluster_manifest_file:
            for document in yaml.safe_load_all(cluster_manifest_file):
                if document['kind'] == 'TalosControlPlane':
                    with open(os.path.join(cluster_secrets_dir, 'controlplane-patches.yaml'), 'w') as cp_patches_file:
                        yaml.dump(
                            document['spec']['controlPlaneConfig']['controlplane']['configPatches'],
                            cp_patches_file
                        )
                if document['kind'] == 'TalosConfigTemplate':
                    with open(os.path.join(cluster_secrets_dir, 'worker-patches.yaml'), 'w') as worker_patches_file:
                        yaml.dump(
                            document['spec']['template']['spec']['configPatches'],
                            worker_patches_file
                        )

        with ctx.cd(cluster_secrets_dir):
            worker_capi_file_name = "worker-capi.yaml"
            cp_capi_file_name = "controlplane-capi.yaml"
            ctx.run(
                "talosctl machineconfig patch worker.yaml --patch @worker-patches.yaml -o {}".format(
                    worker_capi_file_name
                ),
                echo=self._echo
            )
            ctx.run(
                "talosctl machineconfig patch controlplane.yaml --patch @controlplane-patches.yaml -o {}".format(
                    cp_capi_file_name
                ),
                echo=self._echo
            )

            add_talos_hashbang(os.path.join(cluster_secrets_dir, worker_capi_file_name))
            add_talos_hashbang(os.path.join(cluster_secrets_dir, cp_capi_file_name))

            ctx.run("talosctl validate -m cloud -c {}".format(worker_capi_file_name), echo=self._echo)
            ctx.run("talosctl validate -m cloud -c {}".format(cp_capi_file_name), echo=self._echo)

        with open(cluster_manifest_file_name) as cluster_manifest_file:
            documents = list()
            for document in yaml.safe_load_all(cluster_manifest_file):
                if document['kind'] == 'TalosControlPlane':
                    del (document['spec']['controlPlaneConfig']['controlplane']['configPatches'])
                    document['spec']['controlPlaneConfig']['controlplane']['generateType'] = "none"
                    with open(os.path.join(cluster_secrets_dir, cp_capi_file_name)) as talos_cp_config_file:
                        document['spec']['controlPlaneConfig']['controlplane']['data'] = talos_cp_config_file.read()

                if document['kind'] == 'TalosConfigTemplate':
                    del (document['spec']['template']['spec']['configPatches'])
                    document['spec']['template']['spec']['generateType'] = 'none'
                    with open(os.path.join(cluster_secrets_dir, worker_capi_file_name)) as talos_worker_config_file:
                        document['spec']['template']['spec']['data'] = talos_worker_config_file.read()

                documents.append(document)

        with open(self._paths.cluster_capi_static_manifest_file(), 'w') as static_manifest:
            yaml.dump_all(documents, static_manifest, sort_keys=True)

    def patch_template_with_cilium_manifest(self, ctx, echo: bool):
        """
        Patch talos machine config with cilium CNI manifest for inline installation method
        https://www.talos.dev/v1.3/kubernetes-guides/network/deploying-cilium/#method-4-helm-manifests-inline-install
        """
        app_name = 'network-dependencies'
        app_ctrl = ApplicationsCtrl(ctx, self._state, echo, self._cluster)
        hvf = app_ctrl.prepare_network_dependencies(app_name, Namespace.network_services)
        helm_manifest_path = app_ctrl.render_helm_template(hvf, Namespace.network_services)
        with open(helm_manifest_path) as helm_manifest_file:
            helm_manifest = list(yaml.safe_load_all(helm_manifest_file))

        """
          op: add
          path: /cluster/inlineManifests/- # ToDo !!! '0' ? not '-' ?
          value:
            name: cpem-secret
            contents: |
        """
        patch = {
            'op': 'add',
            'path': '/cluster/inlineManifests/-',
            'value': {
                'name': 'cilium-cni',
                'contents': yaml.dump_all(helm_manifest)
            }
        }

        with open(self._paths.cluster_capi_manifest_file()) as cluster_template_file:
            capi_cluster_manifest = list(yaml.safe_load_all(cluster_template_file))
            for document in capi_cluster_manifest:
                if document['kind'] == 'TalosControlPlane':
                    document['spec']['controlPlaneConfig']['controlplane']['configPatches'].append(
                        patch
                    )
                # if document['kind'] == 'TalosConfigTemplate':
                #     for patch in document['spec']['template']['spec']['configPatches']:
                #         if 'name' in patch['value'] and patch['value']['name'] == 'network-services-dependencies':
                #             patch['value']['contents'] = helm_manifest

        with open(self._paths.cluster_capi_manifest_file(), 'w') as cluster_template_file:
            yaml.dump_all(capi_cluster_manifest, cluster_template_file)

    def generate_cluster_spec(self):
        """
        Produces ClusterAPI manifest - ~/.gocy/[Constellation_name][Cluster_name]/cluster_spec.yaml
        In this particular case we are dealing with two kind of config specifications.
        Cluster API one and Talos Linux one.
        As per official CAPI documentation https://cluster-api.sigs.k8s.io/tasks/using-kustomize.html,
        this functionality is currently limited. As of now Kustomize alone can not produce satisfactory result.
        This is why we go with some custom python + jinja template solution.
        """
        repo_paths = RepoPaths()

        with open(repo_paths.capi_control_plane_template()) as cluster_file:
            capi_control_plane_template_yaml = cluster_file.read()

        with open(repo_paths.capi_machines_template()) as md_file:
            capi_machines_template_yaml = md_file.read()

        self.build_capi_manifest(
            self._state.secrets['env'],
            capi_control_plane_template_yaml, capi_machines_template_yaml
        )

    def build_manifest(self, ctx, dev_mode: bool):
        self.generate_cluster_spec()
        self.talosctl_gen_config(ctx)
        if not dev_mode:
            self.patch_template_with_cilium_manifest(ctx, self._echo)

        self.talos_apply_config_patch(ctx)

    def nodes_exist(self, ctx) -> (bool, dict):
        ctx.run("metal device get -o yaml > {}".format(
            self._paths.device_list_file()), echo=self._echo)

        ip_addresses = dict()

        with open(self._paths.device_list_file()) as device_list_file:
            for element in yaml.safe_load(device_list_file):
                if self._cluster.name in element['hostname']:
                    for ip_address in element['ip_addresses']:
                        if ip_address['address_family'] == 4 and ip_address['public'] is True:
                            if CONTROL_PLANE_NODE in element['hostname']:
                                ip_addresses[ip_address['address']] = CONTROL_PLANE_NODE
                            else:
                                ip_addresses[ip_address['address']] = WORKER_NODE

        all_nodes_accounted_for = False

        # print("{} | {}".format(len(ip_addresses), len(list(self.cluster))))

        if len(ip_addresses) >= len(list(self._cluster)):
            all_nodes_accounted_for = True

        return all_nodes_accounted_for, ip_addresses

    def get_secrets(self, ctx):
        nodes_exist, nodes = self.nodes_exist(ctx)
        if not nodes_exist:
            logging.fatal("At least one of the requested cluster nodes are missing")
            return

        with open(self._paths.talosconfig_file()) as talos_config_file:
            talos_config_data = yaml.safe_load(talos_config_file)
            talos_config_data['contexts'][self._cluster.name]['nodes'] = list()
            talos_config_data['contexts'][self._cluster.name]['endpoints'] = list()

        control_plane_node = None
        for key in nodes:
            talos_config_data['contexts'][self._cluster.name]['nodes'].append(key)

            if nodes[key] == CONTROL_PLANE_NODE:
                talos_config_data['contexts'][self._cluster.name]['endpoints'].append(key)
                control_plane_node = key

        with open(self._paths.talosconfig_file(), 'w') as talos_config_file:
            yaml.dump(talos_config_data, talos_config_file)

        ctx.run("talosctl config merge " + self._paths.talosconfig_file(), echo=self._echo)

        kubeconfig_path = self._paths.kubeconfig_file()
        if control_plane_node is None:
            print('Could not produce ' + kubeconfig_path)
            return

        ctx.run("talosctl --talosconfig {} bootstrap --nodes {} | true".format(
            self._paths.talosconfig_file(),
            control_plane_node), echo=self._echo)

        metal = MetalCtrl(self._state, self._echo, self._cluster)
        ctx.run("talosctl --talosconfig {} --nodes {} kubeconfig {}".format(
            self._paths.talosconfig_file(),
            metal.get_vips(VipRole.cp).public_ipv4[0],
            kubeconfig_path
        ), echo=self._echo)

        self.crete_missing_talosconfig(ctx)

        ctx.run("kconf add " + kubeconfig_path, echo=self._echo, pty=True)
        self._state.set_cluster(self._cluster.name)
        
    def crete_missing_talosconfig(self, ctx):
        """
        Workaround for missing talosconfig secret, thrown in TalosControlPlane log
        {
            "namespace": "argo-infra",
            "talosControlPlane": "saturn-control-plane",
            "error": "Secret \"saturn-talosconfig\" not found"
        }
        """
        namespace = Namespace.argocd
        try:
            ctx.run('kubectl --namespace {} create secret generic {}-talosconfig --from-file="{}"'.format(
                namespace,
                self._cluster.name,
                self._paths.talosconfig_file()
            ), echo=self._echo)
        except Failure:
            print("Namespace {} already exists".format(namespace))

    def get_oidc_kubeconfig(self):
        """
        Generates oidc kubeconfigs to be shared with team members.
        """
        kubeconfig_file_path = self._paths.kubeconfig_file()

        with open(kubeconfig_file_path) as kubeconfig_file:
            kubeconfig = dict(yaml.safe_load(kubeconfig_file))

        jinja = JinjaWrapper().jinja
        repo_paths = RepoPaths()

        with open(repo_paths.oidc_template_file()) as oidc_user_tpl_file:
            oidc_user_tpl = jinja.from_string(oidc_user_tpl_file.read())

        secrets = self._state.secrets
        data = {
            'cluster_name': self._cluster.name
        }
        data.update(secrets['idp_auth']['k8s_oidc'])

        oidc_user = yaml.safe_load(oidc_user_tpl.render(data))

        kubeconfig['users'] = [oidc_user]
        kubeconfig['contexts'][0]['context']['user'] = oidc_user['name']
        kubeconfig['contexts'][0]['name'] = "{}@{}".format('oidc', self._cluster.name)
        kubeconfig['current-context'] = list(kubeconfig['contexts'])[0]['name']

        with open(self._paths.kubeconfig_oidc_file(), 'w') as oidc_kubeconfig_file:
            yaml.safe_dump(kubeconfig, oidc_kubeconfig_file)

    def delete_directories(self):
        cluster_dir = self._paths.cluster_dir()
        if not os.path.isdir(cluster_dir):
            return

        print('Directory {}, will be removed together with its contents.'.format(cluster_dir))
        if user_confirmed():
            shutil.rmtree(cluster_dir)

    def delete_k8s_contexts(self, ctx):
        contexts_stdout = ctx.run("kconf list", hide='stdout', echo=self._echo).stdout
        contexts = set([line.strip() for line in contexts_stdout.splitlines()])
        trash_can = set()

        for context in contexts:
            if "@" + self._cluster.name in context:
                trash_can.add(context)

        if len(trash_can) == 0:
            return

        print('Following k8s contexts will be removed:')
        for trash in trash_can:
            print(trash)

        if user_confirmed():
            difference = contexts.difference(trash_can)
            if KIND_CONTEXT_NAME in difference:
                ctx.run("kconf use " + KIND_CONTEXT_NAME)
            else:
                ctx.run("kconf use " + difference.pop())

            for trash in trash_can:
                ctx.run("kconf rm " + trash.replace('*', '').strip(), echo=self._echo, pty=True)

    def delete_talos_contexts(self):
        with open(self._paths.talosconfig_global_file()) as talosconfig_file:
            talosconfig = dict(yaml.safe_load(talosconfig_file))

        for context_name, value in list(talosconfig['contexts'].items()):
            if self._cluster.name in context_name:
                del talosconfig['contexts'][context_name]

        if self._cluster.name in talosconfig['context']:
            talosconfig['context'] = ''

        with open(self._paths.talosconfig_global_file(), 'w') as talosconfig_file:
            yaml.safe_dump(talosconfig, talosconfig_file)


def add_talos_hashbang(filename):
    with open(filename, 'r') as file:
        data = file.read()

    with open(filename, 'w') as file:
        file.write("#!talos\n" + data)