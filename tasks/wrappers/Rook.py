import os.path

import requests
import yaml
from invoke import Context

from tasks.controllers.ApplicationsCtrl import ApplicationsCtrl
from tasks.dao.SystemContext import SystemContext
from tasks.models.ConstellationSpecV01 import Cluster
from tasks.models.Namespaces import Namespace
from tasks.wrappers.Kubectl import Kubectl


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

        krew plugin does not have support for radosgw-admin
        https://rook.io/docs/rook/v1.12/Troubleshooting/krew-plugin/
        """
        self._ctx = ctx
        self._context = context
        self._echo = echo
        self._namespace = Namespace.storage

    def install(self, install: bool, cluster_name: str = None, application_directory='storage'):
        if cluster_name is None:
            cluster = self._context.cluster()
        else:
            cluster = self._context.cluster(cluster_name)

        master_cluster = self._context.constellation.satellites[0]
        initial_context = self._context.cluster()

        if cluster != initial_context:
            self._context.set_cluster(cluster)

        data = {
            'values': {
                'multisite_enabled': cluster != self._context.constellation.bary,
                'applications': [
                    {
                        'realm_name': "{}-harbor".format(cluster.name),
                        'zone_group_name': self._context.constellation.name,
                        'zone_name': cluster.name,
                        'object_store_name': cluster.name,
                        'master_zone': {
                            'defined': cluster != master_cluster,
                            'name': master_cluster.name
                        }
                    },
                    {
                        'realm_name': "{}-nexus".format(cluster.name),
                        'zone_group_name': self._context.constellation.name,
                        'zone_name': cluster.name,
                        'object_store_name': cluster.name,
                        'master_zone': {
                            'defined': cluster != master_cluster,
                            'name': master_cluster.name
                        }
                    },
                    {
                        'realm_name': "{}-artifactory".format(cluster.name),
                        'zone_group_name': self._context.constellation.name,
                        'zone_name': cluster.name,
                        'object_store_name': cluster.name,
                        'master_zone': {
                            'defined': cluster != master_cluster,
                            'name': master_cluster.name
                        }
                    }
                ]
            },
            'deps': {
                '10_rook_crd': {},
                '20_rook_cluster': {
                    'cluster_name': cluster.name,
                    'operator_namespace': application_directory,
                }
            }
        }

        ApplicationsCtrl(self._ctx, self._context, self._echo, cluster=cluster).install_app(
            application_directory, data, Namespace.storage, install)

        self._install_toolbox()

        if cluster != initial_context:
            self._context.set_cluster(initial_context)

    def enable_multisite_storage(self):
        kubectl = Kubectl(self._ctx, self._context, self._echo)
        cluster = self._context.cluster()
        kubectl.cilium_annotate(cluster, Namespace.storage, "rook-ceph-rgw-multisite-{}".format(cluster.name))

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

