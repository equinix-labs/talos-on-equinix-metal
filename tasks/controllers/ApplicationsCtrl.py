import os
from glob import glob
from shutil import copytree, ignore_patterns

import yaml

from tasks.controllers.MetalCtrl import MetalCtrl
from tasks.dao.ProjectPaths import RepoPaths
from tasks.dao.SystemContext import SystemContext
from tasks.helpers import get_jinja, get_file_content_as_b64
from tasks.models.ConstellationSpecV01 import VipRole
from tasks.models.HelmValueFiles import HelmValueFiles
from tasks.models.Namespaces import Namespace
from tasks.wrappers.Helm import Helm


class ApplicationsCtrl:
    _context: SystemContext

    def __init__(self, ctx, context: SystemContext, echo: bool = False):
        self._context = context
        self._echo = echo
        self._paths = self._context.project_paths
        self._repo_paths = RepoPaths()
        self._ctx = ctx

        self._template_file_name = 'values.jinja.yaml'
        self._target_file_name = 'values.yaml'

    def render_values(
            self,
            app_name,
            data,
            namespace,
            app_dir_name=None,
            target_app_suffix=None) -> HelmValueFiles:
        """
        Renders jinja style helm values templates to ~/.gocy/[constellation]/[cluster]/apps to be picked up by Argo.
        """
        if app_dir_name is None:
            app_dir_name = app_name

        source_apps_path = self._repo_paths.apps_dir(app_name)
        target_apps_path = self._paths.apps_dir(
            app_dir_name if not target_app_suffix else app_dir_name + "-" + target_app_suffix)

        copytree(source_apps_path, target_apps_path,
                 ignore=ignore_patterns(self._template_file_name, 'charts'), dirs_exist_ok=True)

        target = os.path.join(target_apps_path, self._target_file_name)

        render_values_file(
                           os.path.join(source_apps_path, self._template_file_name),
                           target,
                           data['values']
        )

        render_values_file(
            self._repo_paths.templates_dir('argo', 'application.jinja.yaml'),
            self._paths.argo_app(app_dir_name + '.yaml'),
            {
                'name': app_name,
                'namespace': Namespace.argocd.value,
                'destination': self._context.cluster.name,
                'target_namespace': namespace,
                'project': self._context.cluster.name,
                'path': os.path.join(self._context.cluster.name, 'apps', app_dir_name),
                'repo_url': "http://gitea-http.gitea:3000/gocy/saturn.git"
            }
        )

        hvf = HelmValueFiles()

        hvf.app = target

        if 'deps' not in data:
            return hvf

        template_paths = glob(os.path.join(source_apps_path, '**', self._target_file_name), recursive=True)
        for template_path in template_paths:
            for dependency_name, dependency_data in data['deps'].items():
                dependency_folder_path = os.path.join('deps', dependency_name)
                if dependency_folder_path in template_path:
                    source = os.path.join(
                        source_apps_path,
                        dependency_folder_path,
                        self._template_file_name
                    )
                    target = os.path.join(
                        target_apps_path,
                        dependency_folder_path,
                        self._template_file_name)

                    render_values_file(
                        source,
                        target,
                        dependency_data
                    )

                    hvf.deps.append(target)

        return hvf

    def install_app(self, app_name: str, data: dict, namespace: Namespace, install: bool):
        value_files = self.render_values(app_name, data, namespace)

        helm = Helm(self._ctx, self._echo)
        helm.install(value_files, app_name, namespace=namespace.value, install=install)

    def get_available(self):
        apps_dirs = glob(self._paths.apps_dir('*'), recursive=True)

        compatible_apps = []
        for apps_dir in apps_dirs:
            if os.path.isfile(os.path.join(apps_dir, self._template_file_name)):
                compatible_apps.append([
                    os.path.basename(apps_dir),
                    apps_dir
                ])

        return compatible_apps

    def render_helm_template(self, app_name: str, hvf: HelmValueFiles, namespace: Namespace) -> str:
        """
        Produces [secrets_dir]/helm_template/manifest.yaml - Helm cilium manifest to be used
        as inlineManifest is Talos machine specification (Helm manifests inline install).
        https://www.talos.dev/v1.4/kubernetes-guides/network/deploying-cilium/#method-4-helm-manifests-inline-install
        """
        # helm_values = prepare_network_dependencies(ctx, manifest_name, Namespace.network_services)
        helm = Helm(self._ctx, self._echo)
        helm_tpl_data = helm.template(hvf.app, app_name, namespace)

        manifest_file_path = self._paths.k8s_manifests(app_name + '.yaml')

        with open(manifest_file_path, 'w') as manifest_file:
            yaml.safe_dump_all(helm_tpl_data, manifest_file)

        return manifest_file_path

    def prepare_network_dependencies(
            self, app_name='network-dependencies',
            namespace: Namespace = Namespace.network_services) -> HelmValueFiles:

        cluster_spec = self._context.cluster
        constellation_spec = self._context.constellation
        ca_dir = self._paths.ca_dir()

        # We have to count form one
        # Error: Unable to connect cluster:
        #   local cluster has the default name (cluster name: jupiter) and/or ID 0 (cluster ID: 0)
        cluster_id = 1
        for index, value in enumerate(constellation_spec):
            if value == cluster_spec:
                cluster_id = cluster_id + index

        metal = MetalCtrl(self._context, self._echo)

        data = {
            'values': {
                'k8s_service_host': metal.get_vips(VipRole.cp).public_ipv4[0],
                'k8s_service_port': '6443',
                'cluster_name': cluster_spec.name,
                'cluster_id': cluster_id,
                'ca_crt': get_file_content_as_b64(os.path.join(ca_dir, 'ca.crt')),
                'ca_key': get_file_content_as_b64(os.path.join(ca_dir, 'ca.key')),
                'hubble_cluster_domain': cluster_spec.name + '.local'
            }
        }

        return self.render_values(app_name, data, namespace=namespace)


def render_values_file(source: str, target: str, data: dict):
    jinja = get_jinja()
    # ctx.run('mkdir -p ' + str(Path(target).parent.absolute()))
    with open(source) as source_file:
        template = jinja.from_string(source_file.read())

    with open(target, 'w') as target_file:
        rendered_list = [line for line in template.render(data).splitlines() if len(line.rstrip()) > 0]
        target_file.write(os.linesep.join(rendered_list))
