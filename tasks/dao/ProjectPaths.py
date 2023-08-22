import logging
import os.path

import git

from tasks.models.ConstellationSpecV01 import VipRole
from tasks.models.Defaults import CONSTELLATION_FILE_SUFFIX


def get_repo_dir() -> str:
    return os.getcwd()


def log_output(intake):
    def capture_result(ref, *args):
        result = intake(ref, *args)
        print("{} | {}".format(intake.__name__, result))
        return result

    return capture_result


class RepoPaths:

    _root: str

    def __init__(self):
        git_repo = git.Repo(os.getcwd(), search_parent_directories=True)
        self._root = git_repo.git.rev_parse("--show-toplevel")

    def templates_dir(self, *path):
        return os.path.join(self._root, 'templates', *path)

    def openssl_cnf_file(self):
        return self.templates_dir('openssl.cnf')

    def capi_control_plane_template(self):
        return self.templates_dir('cluster', 'capi-control-plane.yaml')

    def capi_machines_template(self):
        return self.templates_dir('cluster', 'capi-machines.yaml')

    def apps_dir(self, *path):
        return os.path.join(self._root, 'apps', *path)

    def app_template_file(self, app_name):
        return os.path.join(self.apps_dir(), app_name, 'values.jinja.yaml')

    def oidc_template_file(self):
        return os.path.join(self.templates_dir('k8s_oidc_user.yaml'))

    def oidc_control_plane_template_file(self):
        return os.path.join(self.templates_dir('patch', 'oidc', 'control-plane.jinja.yaml'))

    def coredns_patch_file(self):
        return os.path.join(self.templates_dir('patch', 'coredns', 'configmap.jinja.yaml'))

    def coredns_deployment_patch_file(self):
        return os.path.join(self.templates_dir('patch', 'coredns', 'deployment.jinja.yaml'))


class ProjectPaths:
    _constellation_name: str
    _cluster_name: str
    _root: str

    def __init__(self, constellation_name: str = None, cluster_name: str = None, root=None):
        self._constellation_name = constellation_name
        self._cluster_name = cluster_name
        if root is None:
            self._root = os.environ.get('GOCY_ROOT', os.path.join(
                os.path.expanduser('~'),
                '.gocy'
            ))
        else:
            if os.path.isabs(root):
                self._root = root
            else:
                self._root = os.path.join(
                    os.path.expanduser('~'),
                    root
                )

    # @log_output
    def project_root(self, *paths):
        return os.path.join(self._root, *paths)

    # @log_output
    def secrets_file(self):
        return os.path.join(self.project_root(), 'secrets.yaml')

    # @log_output
    def gcp_token_file(self):
        return os.path.join(self.constellation_dir(), 'gcp_admin_token.json')

    # @log_output
    def state_file(self):
        return os.path.join(self.project_root(), 'state.yaml')

    # @log_output
    def constellation_dir(self):
        return os.path.join(self.project_root(), self._constellation_name)

    # @log_output
    def ca_dir(self):
        return mkdirs(os.path.join(self.constellation_dir(), 'ca'))

    def ca_crt_file(self):
        return os.path.join(self.ca_dir(), 'ca.crt')

    def ca_key_file(self):
        return os.path.join(self.ca_dir(), 'ca.key')

    def openssl_cnf_file(self):
        return os.path.join(self.ca_dir(), 'openssl.cnf')

    # @log_output
    def constellation_file(self, name: str):
        return os.path.join(self.project_root(), "{}{}".format(name, CONSTELLATION_FILE_SUFFIX))

    # @log_output
    def cluster_dir(self):
        return os.path.join(self.constellation_dir(), self._cluster_name)

    # @log_output
    def talosconfig_file(self):
        return os.path.join(self.talos_dir(), 'talosconfig')

    # @log_output
    def talosconfig_global_file(self):
        return os.path.join(self.project_root(), 'talosconfig')

    # @log_output
    def kubeconfig_file(self):
        return os.path.join(self.access_dir(), 'kubeconfig')

    # @log_output
    def kubeconfig_oidc_file(self):
        return os.path.join(self.access_dir(), 'oidc.kubeconfig')

    # @log_output
    def cluster_capi_manifest_file(self):
        return os.path.join(self.cluster_dir(), "capi-manifest.yaml")

    def docker_config_file(self):
        return os.path.join(self.cluster_dir(), "docker.config.json")

    # @log_output
    def device_list_file(self):
        return os.path.join(self.constellation_dir(), "device-list.yaml")

    # @log_output
    def cluster_capi_static_manifest_file(self):
        return os.path.join(mkdirs(self.argo_infra_dir()), "capi-manifest.static.yaml")

    # @log_output
    def k8s_manifests_dir(self):
        return os.path.join(self.cluster_dir(), "k8s_manifests")

    # @log_output
    def k8s_manifest_file(self, app_name):
        return os.path.join(mkdirs(self.k8s_manifests_dir()), "{}.yaml".format(app_name))

    # @log_output
    def patch_dir(self, *paths):
        return mkdirs(os.path.join(self.cluster_dir(), "patch", *paths))

    def patch_mesh_secret_file(self):
        return os.path.join(self.patch_dir(), 'cilium-clustermesh.yaml')

    def patch_bgp_file(self, name):
        return os.path.join(self.patch_dir('bgp'), name)

    def patch_oidc_file(self, name):
        return os.path.join(self.patch_dir('oidc'), name)

    def coredns_patch_file(self):
        return os.path.join(self.patch_dir('coredns'), 'configmap.patch.yaml')

    def coredns_configmap_file(self):
        return os.path.join(self.patch_dir('coredns'), 'configmap.yaml')

    def coredns_deployment_patch_file(self):
        return os.path.join(self.patch_dir('coredns'), 'deployment.yaml')

    # @log_output
    def templates_dir(self):
        return os.path.join(self.cluster_dir(), "templates")

    # @log_output
    def apps_dir(self, *paths):
        return os.path.join(self.cluster_dir(), "apps", *paths)

    # @log_output
    def talos_dir(self):
        return mkdirs(os.path.join(self.cluster_dir(), "talos"))

    # @log_output
    def access_dir(self):
        return os.path.join(self.cluster_dir(), "access")

    # @log_output
    def argo_apps_dir(self):
        return os.path.join(self.cluster_dir(), "argo", "apps")

    # @log_output
    def argo_app(self, *path):
        return os.path.join(mkdirs(self.argo_apps_dir()), *path)

    # @log_output
    def argo_infra_dir(self):
        return os.path.join(self.cluster_dir(), "argo", "infra")

    # @log_output
    def vips_file_by_role(self, address_role: VipRole):
        return os.path.join(mkdirs(self.cluster_dir()), "vips-{}.yaml".format(address_role))

    # @log_output
    def project_vips_file(self):
        return os.path.join(mkdirs(self.constellation_dir()), 'vips-project.yaml')

    def license_dir(self, *paths):
        return self.project_root('license', *paths)

    def sonatype_license_file(self):
        return self.license_dir('sonatype', 'sonatype-license.lic')


def mkdirs(project_dir: str) -> str:
    if not os.path.isdir(project_dir):
        os.makedirs(project_dir, exist_ok=True)
        logging.info("Created directory: " + project_dir)

    return project_dir

