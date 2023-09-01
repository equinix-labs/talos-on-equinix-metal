import os.path

import requests
import yaml
from invoke import Context

from tasks.controllers.ApplicationsCtrl import ApplicationsCtrl
from tasks.dao.ProjectPaths import ProjectPaths
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
        https://github.com/rook/rook/tree/release-1.12/deploy/examples
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
                        'realm_name': "harbor",
                        'zone_group_name': "{}-harbor".format(self._context.constellation.name),
                        'zone_name': "{}-harbor".format(cluster.name),
                        'object_store_name': "{}-harbor".format(cluster.name),
                        'master_zone': {
                            'defined': cluster != master_cluster,
                            'name': "{}-harbor".format(master_cluster.name)
                        }
                    },
                    {
                        'realm_name': "nexus",
                        'zone_group_name': "{}-nexus".format(self._context.constellation.name),
                        'zone_name': "{}-nexus".format(cluster.name),
                        'object_store_name': "{}-nexus".format(cluster.name),
                        'master_zone': {
                            'defined': cluster != master_cluster,
                            'name': "{}-nexus".format(master_cluster.name)
                        }
                    },
                    {
                        'realm_name': "artifactory",
                        'zone_group_name': "{}-artifactory".format(self._context.constellation.name),
                        'zone_name': "{}-artifactory".format(cluster.name),
                        'object_store_name': "{}-artifactory".format(cluster.name),
                        'master_zone': {
                            'defined': cluster != master_cluster,
                            'name': "{}-artifactory".format(master_cluster.name)
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
        master_cluster = self._context.constellation.satellites[0]
        initial_context = self._context.cluster()
        applications = ['artifactory', 'harbor', 'nexus']

        for cluster in self._context.constellation.satellites:
            self._context.set_cluster(cluster)
            for app in applications:
                app_name = "{}-{}".format(cluster.name, app)
                if cluster == master_cluster:
                    kubectl.cilium_annotate_global_service(
                        cluster,
                        Namespace.storage,
                        "rook-ceph-rgw-m-{}".format(app_name)
                    )
                    self._pull_realm_secret(cluster, app)
                else:
                    paths = ProjectPaths(self._context.constellation.name, master_cluster.name)  # ToDo: fix this spaghetti
                    self._ctx.run("kubectl --context admin@{} --namespace {} apply -f {}".format(
                        cluster.name,
                        Namespace.storage,
                        paths.cluster_secret_file("{}.yaml".format(app))
                    ))

        self._context.set_cluster(initial_context)

    def _pull_realm_secret(self, cluster: Cluster, secret_name: str):
        realm_secret_yaml = self._ctx.run(
            "kubectl --context admin@{} --namespace {} "
            "get secret {}-keys -o yaml".format(
                cluster.name,
                Namespace.storage,
                secret_name),
            hide="stdout",
            echo=self._echo).stdout

        realm_secret = dict(yaml.safe_load(realm_secret_yaml))
        del realm_secret['metadata']['creationTimestamp']
        del realm_secret['metadata']['ownerReferences']
        del realm_secret['metadata']['resourceVersion']
        del realm_secret['metadata']['uid']

        paths = ProjectPaths(self._context.constellation.name, cluster.name)
        with open(paths.cluster_secret_file("{}.yaml".format(secret_name)), 'w') as secret_file:
            yaml.dump(realm_secret, secret_file)

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

