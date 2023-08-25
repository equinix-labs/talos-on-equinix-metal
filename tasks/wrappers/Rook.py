import os.path

import requests
import yaml
from invoke import Context

from tasks.controllers.ApplicationsCtrl import ApplicationsCtrl
from tasks.dao.SystemContext import SystemContext
from tasks.models.ConstellationSpecV01 import Cluster
from tasks.models.Namespaces import Namespace


class Rook:
    def __init__(
            self, ctx: Context,
            context: SystemContext,
            echo: bool):
        """
        We will focus on the Multi Site Object Storage - s3 compatible, because simple DR is boring
        https://rook.io/docs/rook/v1.12/Storage-Configuration/Object-Storage-RGW/object-storage/
        https://docs.ceph.com/en/latest/radosgw/multisite/
        https://rook.github.io/docs/rook/v1.12/Storage-Configuration/Object-Storage-RGW/ceph-object-multisite/
        """
        self._ctx = ctx
        self._context = context
        self._echo = echo
        self._namespace = Namespace.storage

    def install(self, install: bool, application_directory='storage'):
        data = {
            'values': {
                'cluster_name': self._context.cluster().name,
                'operator_namespace': application_directory,
                'realm_name': self._context.constellation.name,
                'zone_group_name': self._context.constellation.name,
                'zone_name': self._context.cluster().name
            },
            'deps': {
                'rook': {}
            }
        }

        ApplicationsCtrl(self._ctx, self._context, self._echo).install_app(
            application_directory, data, Namespace.storage, install)

        self._install_toolbox()

    def _install_toolbox(self, branch_name='master'):
        toolbox_deployment_file_path = self._context.project_paths.deployments_ceph_toolbox()
        if not os.path.isfile(toolbox_deployment_file_path):
            url = 'https://raw.githubusercontent.com/rook/rook/{}/deploy/examples/toolbox.yaml'.format(branch_name)
            r = requests.get(url)
            if r.status_code != 200:
                print("Check the toolbox URL: " + url)
                return

            data = dict(yaml.safe_load(r.text))
            data['metadata']['namespace'] = Namespace.storage.value
            with open(toolbox_deployment_file_path, 'w') as toolbox_deployment_file:
                yaml.dump(data, toolbox_deployment_file)

        self._ctx.run("kubectl apply -f {}".format(toolbox_deployment_file_path), echo=self._echo)

    def _cmd_radosgw_admin(self, cluster: Cluster, namespace: Namespace, command: str):
        self._ctx.run(
            "kubectl --context admin@{} --namespace {} exec deployment/rook-ceph-tools -- radosgw-admin {}".format(
                cluster.name,
                namespace.value,
                command
            ))

    def rgwa_sync_status(self, cluster: Cluster, namespace: Namespace):
        self._cmd_radosgw_admin(cluster, namespace, 'sync status')

    def _cmd_ceph(self, cluster: Cluster, namespace: Namespace, command: str):
        self._ctx.run(
            "kubectl --context admin@{} --namespace {} exec deployment/rook-ceph-tools -- ceph {}".format(
                cluster.name,
                namespace.value,
                command
            ), echo=self._echo)

    def status_osd(self, cluster: Cluster, namespace: Namespace):
        self._cmd_ceph(cluster, namespace, 'osd status')

