import logging

import yaml
from invoke import Context, Failure

from tasks.controllers.ApplicationsCtrl import ApplicationsCtrl
from tasks.dao.ProjectPaths import ProjectPaths
from tasks.dao.SystemContext import SystemContext
from tasks.helpers import get_fqdn, str_presenter
from tasks.models.ConstellationSpecV01 import Cluster
from tasks.models.Namespaces import Namespace
from tasks.wrappers.Kubectl import Kubectl

yaml.add_representer(str, str_presenter)
yaml.representer.SafeRepresenter.add_representer(str, str_presenter)  # to use with safe_dump


class Databases:
    def __init__(
            self, ctx: Context,
            context: SystemContext,
            echo: bool = False,
            application_directory: str = 'dbs'):

        self._ctx = ctx
        self._context = context
        self._echo = echo
        self._application_directory = application_directory

    def install(self, install: bool, ingress_enabled: bool = False):
        """
        None of the tested Repository Managers work with CockroachDB. Until they do we go with
        https://cloudnative-pg.io/documentation/current
        https://github.com/cloudnative-pg/charts
        """
        master_cluster = self._context.constellation.satellites[0]
        secrets = self._context.secrets
        context = self._context.cluster()

        for cluster in self._context.constellation.satellites:
            self._context.set_cluster(cluster)
            if master_cluster != cluster:
                self._create_postgres_master_replication_secret(master_cluster)

            data = {
                'values': {
                    'cluster_name': cluster.name,
                    'external_clusters': self._context.satellites_except(cluster) if cluster != master_cluster else [],
                    'replica_enabled': True if cluster != master_cluster else False,
                    'primary_name': master_cluster.name
                },
                'deps': {
                    'cloudnative_pg': {
                        'enabled': True,
                    },
                    'cockroachdb': {
                        'cockroachdb': self._context.secrets['dbs']['cockroachdb'],
                        'cluster_domain': cluster.name + '.local',
                        'cluster_name': self._context.constellation.name,
                        'locality': cluster.name,
                        'cockroach_fqdn': get_fqdn('cockroach', secrets, cluster),
                        'oauth_fqdn': get_fqdn('oauth', secrets, cluster),
                        'ca_issuer_name': "{}-ca-issuer".format(self._context.constellation.name),
                        'first_cluster': self._context.constellation.bary.name,
                        'ingress_enabled': ingress_enabled,
                        'replica_count': 3,
                        'join_list': '[]' if cluster == self._context.constellation.bary else '',
                        'tls_enabled': False,  # ToDo: Enable, remember that this will require DB clients to use certificates as well
                    },
                    'galera': {
                        'cluster_domain': cluster.name + '.local',
                        'mariadb': self._context.secrets['dbs']['mariadb'],
                        'cluster_name': self._context.constellation.name,
                    }
                }
            }

            ApplicationsCtrl(self._ctx, self._context, self._echo, cluster=cluster).install_app(
                self._application_directory, data, Namespace.database, install)

            if master_cluster == cluster:
                self._pull_postgres_master_certificate(master_cluster)

        self._patch_cluster_service()
        self._context.set_cluster(context)

    def _create_postgres_master_replication_secret(self, cluster: Cluster):
        paths = ProjectPaths(self._context.constellation.name, cluster.name)
        self._ctx.run("kubectl --context admin@{} apply -f {}".format(
            cluster.name,
            paths.postgres_master_replication_secret()
        ), echo=self._echo)

    def _pull_postgres_master_certificate(self, cluster: Cluster):
        replication_secret_yaml = self._ctx.run(
            "kubectl --context admin@{} --namespace {} get secrets postgres-{}-replication -o yaml".format(
                cluster.name,
                Namespace.database,
                cluster.name,
            ), hide="stdout", echo=self._echo).stdout
        replication_secret = dict(yaml.safe_load(replication_secret_yaml))
        del (replication_secret['metadata']['creationTimestamp'])
        del (replication_secret['metadata']['resourceVersion'])
        del (replication_secret['metadata']['uid'])
        del (replication_secret['metadata']['ownerReferences'])

        paths = ProjectPaths(self._context.constellation.name, cluster.name)
        with open(paths.postgres_master_replication_secret(), 'w') as replication_secret_file:
            yaml.dump(replication_secret, replication_secret_file)

    def _patch_cluster_service(self):
        kubectl = Kubectl(self._ctx, self._context, self._echo)
        for cluster in self._context.constellation.satellites:
            kubectl.cilium_annotate_global_service(cluster, Namespace.database, "postgres-{}-rw".format(cluster.name))

    def uninstall(self):
        context = self._context.cluster()
        for cluster in self._context.constellation.satellites:
            self._context.set_cluster(cluster)
            try:
                self._ctx.run(
                    "helm --namespace {} uninstall {}".format(Namespace.database, self._application_directory),
                    echo=self._echo)
            except Failure:
                logging.info("Already gone...")

            self._ctx.run("kubectl --namespace {} delete pvc --all".format(Namespace.database),
                          echo=self._echo)

        self._context.set_cluster(context)

    def port_forward_cockroach_db(self, cluster_name: str):
        cluster = self._context.cluster(cluster_name)
        index = self._context.constellation.satellites.index(cluster)

        self._ctx.run("kubectl --context admin@{} --namespace {} port-forward"
                      " service/dbs-cockroachdb-public 2625{}:26257".format(
                            cluster.name,
                            Namespace.database,
                            index
                        ), echo=self._echo)

    def port_forward_maria_db(self, cluster_name: str):
        cluster = self._context.cluster(cluster_name)
        index = self._context.constellation.satellites.index(cluster)

        self._ctx.run("kubectl --context admin@{} --namespace {} port-forward"
                      " service/dbs-mariadb-galera 330{}:3306".format(
                            cluster.name,
                            Namespace.database,
                            index
                        ), echo=self._echo)

    def port_forward_ui(self, cluster_name: str):
        cluster = self._context.cluster(cluster_name)
        index = self._context.constellation.satellites.index(cluster)

        self._ctx.run("kubectl --context admin@{} --namespace {} port-forward dbs-cockroachdb-0 808{}:8080".format(
            cluster.name,
            Namespace.database,
            index
        ), echo=self._echo)

    def postgres_create_db(self, cluster: Cluster, db_name: str):
        try:
            self._ctx.run(
                "kubectl "
                "--context admin@{} "
                "--namespace {} exec -it services/postgres-titan-rw -- "
                "psql -c 'create database {};'".format(
                    cluster.name,
                    Namespace.database,
                    db_name
                ), echo=self._echo)
        except Failure:
            logging.info("Already exists")

    def postgres_create_user(self, cluster: Cluster, user_name: str, user_pass: str):
        try:
            self._ctx.run(
                "kubectl "
                "--context admin@{} "
                "--namespace {} exec -it services/postgres-titan-rw -- "
                "psql -c \"create user {} with encrypted password '{}';\"".format(
                    cluster.name,
                    Namespace.database,
                    user_name,
                    user_pass
                ), echo=self._echo)
        except Failure:
            logging.info("Already exists")

    def postgres_grant(self, cluster: Cluster, db_name: str, user_name: str):
        # https://github.com/golang-migrate/migrate/issues/826
        try:
            self._ctx.run(
                "kubectl "
                "--context admin@{} "
                "--namespace {} exec -it services/postgres-titan-rw -- "
                "psql -c \"grant all privileges on database {} to {}; alter database {} owner to {};\"".format(
                    cluster.name,
                    Namespace.database,
                    db_name,
                    user_name,
                    db_name,
                    user_name
                ), echo=self._echo)
        except Failure:
            logging.info("Already exists")

