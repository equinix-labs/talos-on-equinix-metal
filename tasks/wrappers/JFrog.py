import logging

from invoke import Context, Failure

from tasks.controllers.ApplicationsCtrl import ApplicationsCtrl
from tasks.dao.SystemContext import SystemContext
from tasks.helpers import get_fqdn
from tasks.models.ConstellationSpecV01 import Cluster
from tasks.models.Namespaces import Namespace
from tasks.wrappers.Databases import Databases

artifactory_registry = 'artifactory_registry'
artifactory_oss_registry = 'artifactory_oss_registry'


class JFrog:
    def __init__(
            self, ctx: Context,
            context: SystemContext,
            echo: bool = False,
            application_directory: str = 'jfrog'):
        """
        https://github.com/devopshq/artifactory
        https://jfrog.com/help/r/jfrog-installation-setup-documentation/install-artifactory-ha-with-helm
        """
        self._ctx = ctx
        self._context = context
        self._echo = echo
        self._application_directory = application_directory
        self._master_cluster = self._context.constellation.satellites[0]

    def _create_namespace(self):
        try:
            self._ctx.run("kubectl create namespace {}".format(Namespace.jfrog), echo=self._echo)
        except Failure:
            logging.info("Already exists")

    def _create_dbs(self, databases: Databases, db_master_cluster: Cluster):
        databases.postgres_create_user(
            db_master_cluster,
            self._context.secrets['jfrog']['db']['user'],
            self._context.secrets['jfrog']['db']['pass'],
        )
        databases.postgres_create_db(
            db_master_cluster,
            artifactory_registry
        )
        databases.postgres_create_db(
            db_master_cluster,
            artifactory_oss_registry
        )
        databases.postgres_grant(
            db_master_cluster,
            artifactory_registry,
            self._context.secrets['jfrog']['db']['user']
        )
        databases.postgres_grant(
            db_master_cluster,
            artifactory_oss_registry,
            self._context.secrets['jfrog']['db']['user']
        )

    def _create_db_secret(self):
        """
        For some reason Artifactory helm chart fails to create access secrets for external DB
        """
        try:
            self._ctx.run("kubectl --namespace {} create secret generic {} --from-literal={}={}".format(
                Namespace.jfrog,
                self._context.secrets['jfrog']['db']['user'],
                self._context.secrets['jfrog']['db']['user'],
                self._context.secrets['jfrog']['db']['pass']
            ), echo=self._echo)
        except Failure:
            logging.info("Already exists")

        try:
            self._ctx.run("kubectl --namespace {} create secret generic {} --from-literal={}={}".format(
                Namespace.jfrog,
                'artifactory-database-creds',
                'db-url',
                "'jdbc:postgresql://postgres-{}-rw.{}:5432'".format(
                    self._context.constellation.satellites[0].name,
                    Namespace.database)
                ), echo=self._echo)
        except Failure:
            logging.info("Already exists")

    def install(self, install: bool):
        cluster = self._context.cluster()

        self._create_namespace()
        if cluster == self._master_cluster:
            # self._create_dbs(Databases(self._ctx, self._context, self._echo), cluster)
            # self._create_bucket(cluster, 'artifactory', install)
            pass

        # self._create_db_secret()
        self._install_enterprise(cluster, install)

    def _create_bucket(self, cluster: Cluster, app_name: str, install: bool):
        data = {
            'values': {
                'object_store_name': 'm-{}-{}'.format(cluster.name, app_name),
                'app_name': app_name
            }
        }
        ApplicationsCtrl(self._ctx, self._context, self._echo).install_app(
            'object-bucket', data, Namespace.jfrog, install, '{}-bucket'.format(app_name))

    def _install_oss(self, cluster: Cluster, install: bool):
        data = {
            'values': {
                    'fqdn': get_fqdn('artifactory-oss', self._context.secrets, cluster),
                    'artifactory': self._context.secrets['jfrog']['artifactory']
                }
        }
        ApplicationsCtrl(self._ctx, self._context, self._echo).install_app(
            'jfrog-oss', data, Namespace.jfrog, install)

    def _install_enterprise(self, cluster: Cluster, install: bool):
        data = {
            'values': {},
            'deps': {
                '10_important_stuff': {
                    'pvc_name': 'artifactory-data-volume'
                },
                '20_artifactory': {
                    'fqdn': get_fqdn('artifactory', self._context.secrets, cluster),
                    'db_url': "jdbc:postgresql://postgres-{}-rw.{}/{}".format(
                        self._master_cluster.name,
                        Namespace.database,
                        artifactory_registry
                    ),
                    'jfrog': self._context.secrets['jfrog']
                }
            }
        }
        ApplicationsCtrl(self._ctx, self._context, self._echo).install_app(
            self._application_directory, data, Namespace.jfrog, install)

    def uninstall(self):
        try:
            self._ctx.run("helm uninstall --namespace {} {}".format(Namespace.jfrog, 'artifactory'), echo=self._echo)
        except Failure:
            logging.info('Most likely already gone...')
