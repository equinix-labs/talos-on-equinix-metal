import json

import yaml
from invoke import Context, Failure

from tasks.controllers.ApplicationsCtrl import ApplicationsCtrl
from tasks.dao.ProjectPaths import RepoPaths
from tasks.dao.SystemContext import SystemContext
from tasks.helpers import get_fqdn
from tasks.models.Namespaces import Namespace
from tasks.wrappers.JinjaWrapper import JinjaWrapper


def _render_dashboard(repo_paths: RepoPaths, jinja: JinjaWrapper, dashboard_name: str, data: dict) -> str:
    return jinja.render_str(repo_paths.grafana_dashboard('{}.jinja.json'.format(dashboard_name)), data)


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
                    'dashboards': self._render_dashboards(),
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

    def _render_dashboards(self) -> list[dict]:
        """
        There is an issue with grafana dashboards, it looks like I'm hitting
        https://github.com/grafana/helm-charts/issues/313
        If dashboards are specified as 'gnetId' in grafana helm chart
        https://rook.io/docs/rook/v1.12/Storage-Configuration/Monitoring/ceph-monitoring/#grafana-dashboards
        then the dashboard 'uid' is not properly updated that results in dashboards overwriting each others data.
        We have a set of dashboards per cluster, grouped within a folder, named with cluster name.
        As a workaround, dashboards jsons were turned into templates,
        once rendered are passed as raw json into the helm chart.
        """
        repo_paths = RepoPaths()
        jinja = JinjaWrapper(variable_start_string="#{", variable_end_string="}#")
        dashboards = list()
        for cluster in self._context.constellation:
            datasource_uid = 'prometheus' if cluster == self._context.constellation.bary else '{}Prometheus'.format(
                cluster.name)

            dashboards.append({
                'name': cluster.name,
                'rgw': _render_dashboard(repo_paths, jinja, 'ceph_rgw', {
                    'title': 'rgw',
                    'datasource_uid': datasource_uid
                }),
                'cluster': _render_dashboard(repo_paths, jinja, 'ceph_cluster', {
                    'title': 'cluster',
                    'datasource_uid': datasource_uid
                }),
                'pools': _render_dashboard(repo_paths, jinja, 'ceph_pools', {
                    'title': 'poold',
                    'datasource_uid': datasource_uid
                }),
            })

        return dashboards

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
