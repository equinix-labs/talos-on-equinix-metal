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


def get_chart_name(dependency_folder_path: str) -> str:
    with open(os.path.join(dependency_folder_path, 'Chart.yaml')) as dependency_chart_file:
        chart = yaml.safe_load(dependency_chart_file)
        return chart['name']


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
            application_directory: str,
            data: dict,
            namespace: Namespace,
            application_name: str = None,
            target_app_suffix: str = None) -> HelmValueFiles:
        """
        Renders jinja templated helm values.jinja.yaml files to ~/.gocy/[constellation]/[cluster]/apps/[app_dir],
        so that they can be later on picked to be picked up by Argo, once Argo is up.
        """
        source_apps_path = self._repo_paths.apps_dir(application_directory)
        if application_name is None:
            application_name = get_chart_name(source_apps_path)

        target_apps_path = self._paths.apps_dir(
            application_directory if not target_app_suffix else application_name + "-" + target_app_suffix)

        copytree(source_apps_path, target_apps_path,
                 ignore=ignore_patterns(self._template_file_name, 'charts'), dirs_exist_ok=True)

        values_file_path = os.path.join(target_apps_path, self._target_file_name)

        render_values_file(
                           os.path.join(source_apps_path, self._template_file_name),
                           values_file_path,
                           data['values']
        )

        hvf = HelmValueFiles(
            application_name if application_name else get_chart_name(target_apps_path),
            values_file_path
        )

        render_values_file(
            self._repo_paths.templates_dir('argo', 'application.jinja.yaml'),
            self._paths.argo_app(application_name + '.yaml'),
            {
                'name': hvf.app.name,
                'namespace': Namespace.argocd.value,
                'destination': self._context.cluster().name,
                'target_namespace': namespace.value,
                'project': self._context.cluster().name,
                'path': os.path.join(self._context.cluster().name, 'apps', application_name),
                'repo_url': "http://gitea-http.gitea:3000/gocy/saturn.git"
            }
        )

        if 'deps' not in data:
            return hvf

        template_paths = glob(os.path.join(source_apps_path, '**', self._template_file_name), recursive=True)

        for template_path in template_paths:
            for dependency_name, dependency_data in data['deps'].items():
                dependency_folder_path = os.path.join('deps', dependency_name)
                if dependency_folder_path in template_path:
                    source = os.path.join(
                        source_apps_path,
                        dependency_folder_path,
                        self._template_file_name
                    )
                    values_file_path = os.path.join(
                        target_apps_path,
                        dependency_folder_path,
                        self._target_file_name)

                    render_values_file(
                        source,
                        values_file_path,
                        dependency_data
                    )

                    hvf.add_dependency(
                        get_chart_name(os.path.join(target_apps_path, dependency_folder_path)),
                        values_file_path
                    )

        return hvf

    def install_app(self, application_directory: str,
                    data: dict, namespace: Namespace, install: bool,
                    application_name: str = None, target_app_suffix: str = None):
        hvf = self.render_values(application_directory, data, namespace, application_name, target_app_suffix)

        helm = Helm(self._ctx, self._echo)
        if install:
            helm.install(hvf, install, namespace.value)

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

    def helm_namespace_fix(self, app_name: str, namespace: Namespace):
        """
        The following is a naive workaround for https://github.com/helm/helm/issues/10737#issuecomment-1062899126
        The problem is that 'helm template' does not work well with '--namespace' in some cases.
        It appears that MetalLB chart is susceptible to this issue. As a workaround we read the generated helm template
        and update the namespaced resources with our namespace.
        """
        api_resources = self._ctx.run('kubectl api-resources --namespaced=true', echo=self._echo, hide='stdout').stdout
        kinds = list()
        for line in api_resources.splitlines():
            columns = line.split()
            for column, value in enumerate(columns):
                if column == len(columns)-1:
                    kinds.append(value)

        manifest_file_path = self._paths.k8s_manifest_file(app_name)
        with open(manifest_file_path) as manifest_file:
            manifests = list(yaml.safe_load_all(manifest_file))

        for manifest in manifests:
            if manifest['kind'] in kinds:
                manifest['metadata']['namespace'] = namespace.value

        with open(manifest_file_path, 'w') as manifest_file:
            yaml.safe_dump_all(manifests, manifest_file)

    def render_helm_template(self, hvf: HelmValueFiles, namespace: Namespace) -> str:
        """
        Produces [secrets_dir]/helm_template/manifest.yaml - Helm cilium manifest to be used
        as inlineManifest is Talos machine specification (Helm manifests inline install).
        https://www.talos.dev/v1.4/kubernetes-guides/network/deploying-cilium/#method-4-helm-manifests-inline-install
        """
        # helm_values = prepare_network_dependencies(ctx, manifest_name, Namespace.network_services)
        helm = Helm(self._ctx, self._echo)
        helm_tpl_data = helm.template(hvf.app, namespace)

        manifest_file_path = self._paths.k8s_manifest_file(hvf.app.name)

        with open(manifest_file_path, 'w') as manifest_file:
            yaml.safe_dump_all(helm_tpl_data, manifest_file)

        self.helm_namespace_fix(hvf.app.name, namespace)

        return manifest_file_path

    def prepare_network_dependencies(
            self, app_name='network-dependencies',
            namespace: Namespace = Namespace.network_services) -> HelmValueFiles:

        cluster_spec = self._context.cluster()
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
