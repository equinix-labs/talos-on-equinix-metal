import yaml
from invoke import Context, Failure

from tasks.controllers.ApplicationsCtrl import ApplicationsCtrl
from tasks.dao.SystemContext import SystemContext
from tasks.helpers import get_fqdn
from tasks.models.ConstellationSpecV01 import Cluster
from tasks.models.Namespaces import Namespace


class Observability:
    def __init__(
            self, ctx: Context,
            context: SystemContext,
            echo: bool):
        """
        We are using:
        https://artifacthub.io/packages/helm/prometheus-community/kube-prometheus-stack

        Grafana is installed only on master/bary cluster, together with prometheus.
        Workload clusters get prometheus only. Single grafana is used to present all constellation stats.
        """
        self._ctx = ctx
        self._context = context
        self._echo = echo
        self._namespace = Namespace.observability

    def install(self, install: bool, cluster_name: str = None, application_directory: str = 'observability'):
        master_cluster = self._context.constellation.bary

        initial_cluster = self._context.cluster()
        secrets = self._context.secrets

        if cluster_name is not None:
            clusters = [self._context.cluster(cluster_name)]
        else:
            clusters = list(self._context.constellation)
            clusters.reverse()
        for cluster in clusters:
            self._context.set_cluster(cluster)

            we_have_storage = self._we_have_storage()
            data = {
                'values': {
                    'oauth_fqdn': get_fqdn('oauth', secrets, cluster),
                    'grafana_fqdn': get_fqdn('grafana', secrets, cluster),
                    'grafana_enabled': master_cluster == cluster,
                    'workload_cluster': master_cluster != cluster,
                    'satellites': self._context.constellation.satellites,
                    'we_have_storage': we_have_storage,

                },
                'deps': {
                    'external_clusters': {
                        'external_clusters': self._context.constellation.satellites if master_cluster == cluster else []
                    }
                }
            }
            data['values'].update(secrets['grafana'])

            ApplicationsCtrl(self._ctx, self._context, self._echo, cluster).install_app(
                application_directory, data, Namespace.observability, install, '{}-{}'.format(
                    'obs', cluster.name[:4]
                ))

        self._context.set_cluster(initial_cluster)

    def _we_have_storage(self) -> bool:
        """
        We need to know if we have rook/ceph enabled so that we could enable persistence in
        prometheus. This is due to circular dependency -> prometheus could use storage, but it is with prometheus
        that we plan to scrape storage stats.
        """
        try:
            ceph_bucket_class_yaml = self._ctx.run(
                "kubectl get StorageClasses ceph-bucket -o yaml", hide="stdout", echo=self._echo).stdout
            ceph_bucket_class = dict(yaml.safe_load(ceph_bucket_class_yaml))
            return bool(ceph_bucket_class)
        except Failure:
            return False
