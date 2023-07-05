import os

import yaml

from tasks.controllers.MetalCtrl import MetalCtrl
from tasks.dao.SystemContext import SystemContext
from tasks.dao.ProjectPaths import ProjectPaths, RepoPaths
from tasks.helpers import get_cpem_config_yaml, get_jinja, get_secret_envs
from tasks.models.ConstellationSpecV01 import Cluster, Constellation, VipRole
from tasks.models.Defaults import KIND_CLUSTER_NAME
from tasks.models.Namespaces import Namespace

_CLUSTER_MANIFEST_FILE_NAME = "cluster-manifest.yaml"
_CLUSTER_MANIFEST_STATIC_FILE_NAME = "cluster-manifest.static-config.yaml"


class ClusterCtrl:
    state: SystemContext
    constellation: Constellation
    cluster: Cluster
    paths: ProjectPaths
    echo: bool

    def __init__(self, state: SystemContext, echo: bool):
        self.state = state
        self.constellation = state.constellation
        self.cluster = state.cluster
        self.paths = state.project_paths
        self.echo = echo

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
                        patch['value']['dnsDomain'] = "{}.local".format(self.cluster.name)
                        patch['value']['podSubnets'] = self.cluster.pod_cidr_blocks
                        patch['value']['serviceSubnets'] = self.cluster.service_cidr_blocks
            if resource['kind'] == 'TalosConfigTemplate':
                patches = resource['spec']['template']['spec']['configPatches']
                for patch in patches:
                    if patch['path'] == '/cluster/network':
                        patch['value']['dnsDomain'] = "{}.local".format(self.cluster.name)
                        patch['value']['podSubnets'] = self.cluster.pod_cidr_blocks
                        patch['value']['serviceSubnets'] = self.cluster.service_cidr_blocks
            if resource['kind'] == 'Cluster':
                resource['spec']['clusterNetwork']['pods']['cidrBlocks'] = self.cluster.pod_cidr_blocks
                resource['spec']['clusterNetwork']['services']['cidrBlocks'] = self.cluster.service_cidr_blocks

        return cluster_manifest

    def talosctl_gen_config(self, ctx):
        """
        Produces initial Talos machine configuration, that later on will be patched with custom cluster settings.
        """
        equinix = MetalCtrl(self.state, self.echo)

        with ctx.cd(self.paths.cluster_dir()):
            ctx.run(
                "talosctl gen config {} https://{}:6443 | true".format(
                    self.cluster.name,
                    equinix.get_vips(VipRole.cp).public_ipv4[0]
                ),
                echo=self.echo
            )

    def build_capi_manifest(self, secrets, cluster_jinja_template, _md_yaml):
        metal_ctrl = MetalCtrl(self.state, self.echo)

        data = {
            'TOEM_CPEM_SECRET': get_cpem_config_yaml(),
            'TOEM_CP_ENDPOINT': metal_ctrl.get_vips(VipRole.cp).public_ipv4[0],
            'SERVICE_DOMAIN': "{}.local".format(self.cluster.name),
            'CLUSTER_NAME': self.cluster.name,
            'METRO': self.cluster.metro,
            'CONTROL_PLANE_NODE_TYPE': self.cluster.control_nodes[0].plan,
            'CONTROL_PLANE_MACHINE_COUNT': self.cluster.control_nodes[0].count,
            'TALOS_VERSION': self.cluster.talos,
            'CPEM_VERSION': self.cluster.cpem,
            'KUBERNETES_VERSION': self.cluster.kubernetes,
            'namespace': Namespace.argocd
        }
        data.update(secrets)

        jinja = get_jinja()
        cluster_yaml_tpl = jinja.from_string(cluster_jinja_template)
        cluster_yaml = cluster_yaml_tpl.render(data)

        for worker_node in self.cluster.worker_nodes:
            worker_yaml_tpl = jinja.from_string(_md_yaml)
            data['machine_name'] = "{}-machine-{}".format(
                self.cluster.name,
                worker_node.plan.replace('.', '-'))  # ToDo: CPEM blows up if there are dots in machine name
            data['WORKER_NODE_TYPE'] = worker_node.plan
            data['WORKER_MACHINE_COUNT'] = worker_node.count
            cluster_yaml = "{}\n{}".format(cluster_yaml, worker_yaml_tpl.render(data))

        cluster_manifest = list(yaml.safe_load_all(cluster_yaml))

        self.patch_cluster_spec_network(cluster_manifest)

        with open(self.paths.capi_manifest_file(), 'w') as cluster_template_file:
            yaml.dump_all(cluster_manifest, cluster_template_file)

    def talos_apply_config_patch(self, ctx):
        cluster_secrets_dir = self.paths.cluster_dir()
        cluster_manifest_file_name = self.paths.cluster_capi_manifest_file()

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
                echo=True
            )
            ctx.run(
                "talosctl machineconfig patch controlplane.yaml --patch @controlplane-patches.yaml -o {}".format(
                    cp_capi_file_name
                ),
                echo=True
            )

            add_talos_hashbang(os.path.join(cluster_secrets_dir, worker_capi_file_name))
            add_talos_hashbang(os.path.join(cluster_secrets_dir, cp_capi_file_name))

            ctx.run("talosctl validate -m cloud -c {}".format(worker_capi_file_name))
            ctx.run("talosctl validate -m cloud -c {}".format(cp_capi_file_name))

        with open(cluster_manifest_file_name) as cluster_manifest_file:
            documents = list()
            for document in yaml.safe_load_all(cluster_manifest_file):
                if document['kind'] == 'TalosControlPlane':
                    del (document['spec']['controlPlaneConfig']['controlplane']['configPatches'])
                    document['spec']['controlPlaneConfig']['controlplane']['generateType'] = "none"
                    with open(os.path.join(cluster_secrets_dir, cp_capi_file_name), 'r') as talos_cp_config_file:
                        document['spec']['controlPlaneConfig']['controlplane']['data'] = talos_cp_config_file.read()

                if document['kind'] == 'TalosConfigTemplate':
                    del (document['spec']['template']['spec']['configPatches'])
                    document['spec']['template']['spec']['generateType'] = 'none'
                    with open(os.path.join(cluster_secrets_dir, worker_capi_file_name), 'r') as talos_worker_config_file:
                        document['spec']['template']['spec']['data'] = talos_worker_config_file.read()

                documents.append(document)

        with open(cluster_manifest_static_file_name, 'w') as static_manifest:
            # yaml.safe_dump_all(documents, static_manifest, sort_keys=True)
            # ToDo: pyyaml for some reason when used with safe_dump_all dumps the inner multiline string as
            # single line long string
            # spec:
            #   template:
            #     spec:
            #       data: "#!talos\ncluster:\n  ca:\n
            #
            # instead of a multiline string
            yaml.dump_all(documents, static_manifest, sort_keys=True)

    def generate_cluster_spec(self):
        """
        Produces ClusterAPI manifest - ~/.gocy/[Constellation_name][Cluster_name]/cluster_spec.yaml
        In this particular case we are dealing with two kind of config specifications. Cluster API one
        and Talos Linux one. As per official CAPI documentation https://cluster-api.sigs.k8s.io/tasks/using-kustomize.html,
        this functionality is currently limited. As of now Kustomize alone can not produce satisfactory result.
        This is why we go with some custom python + jinja template solution.
        """

        repo_paths = RepoPaths()

        with open(repo_paths.capi_control_plane_template()) as cluster_file:
            capi_control_plane_template_yaml = cluster_file.read()

        with open(repo_paths.capi_machines_template()) as md_file:
            capi_machines_template_yaml = md_file.read()

        secrets = get_secret_envs()

        self.build_capi_manifest(
            secrets,
            capi_control_plane_template_yaml, capi_machines_template_yaml
        )

    def build_manifest(self, ctx, dev_mode: bool):
        # clean(ctx, constellation, cluster)
        self.generate_cluster_spec()


def set_context(ctx, cluster: Cluster, echo=True):
    if 'kind' in cluster.name:
        ctx.run("kconf use " + cluster.name, echo=echo)
    else:
        ctx.run("kconf use admin@" + cluster.name, echo=echo)
        ctx.run("talosctl config context " + cluster.name, echo=echo)


def context_set_bary(ctx, local_state: SystemContext):
    """
    Switch k8s context to management(bary) cluster
    """
    constellation = local_state.constellation
    set_context(ctx, constellation.bary)


def context_set_kind(ctx):
    """
    Switch k8s context to local(kind) management(ClusterAPI) cluster
    """
    set_context(ctx, Cluster(name=KIND_CLUSTER_NAME))


def add_talos_hashbang(filename):
    with open(filename, 'r') as file:
        data = file.read()

    with open(filename, 'w') as file:
        file.write("#!talos\n" + data)