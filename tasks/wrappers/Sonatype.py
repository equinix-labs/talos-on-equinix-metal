import logging

from invoke import Context, Failure

from tasks.controllers.ApplicationsCtrl import ApplicationsCtrl
from tasks.dao.SystemContext import SystemContext
from tasks.helpers import get_fqdn
from tasks.models.ConstellationSpecV01 import Cluster
from tasks.models.Namespaces import Namespace
from tasks.wrappers.Databases import Databases
from tasks.wrappers.Rook import Rook

nexus_registry = 'nexus_registry'


class Sonatype:
    def __init__(
            self, ctx: Context,
            context: SystemContext,
            echo: bool = False,
            cluster_name: str = None):
        """
        https://github.com/devopshq/artifactory
        https://jfrog.com/help/r/jfrog-installation-setup-documentation/install-artifactory-ha-with-helm
        """
        self._ctx = ctx
        self._context = context
        self._echo = echo
        self._master_cluster = self._context.constellation.satellites[0]

        if cluster_name is not None:
            self._satellites = [self._context.cluster(cluster_name)]

    def _create_namespace(self):
        try:
            self._ctx.run('kubectl create namespace {}'.format(
                Namespace.sonatype
            ), echo=self._echo)
        except Failure:
            logging.info("Already exists")

    def _create_license_secret(self):
        try:
            self._ctx.run('kubectl --namespace {} create secret generic {} --from-file={}={}'.format(
                Namespace.sonatype,
                'nxrm-license',
                'nxrm-license.lic',
                self._context.project_paths.sonatype_license_file()
            ), echo=self._echo)
        except Failure:
            logging.info("Already exists")

    def install(self, install: bool):
        cluster = self._context.cluster()

        self._create_namespace()
        self._create_license_secret()

        rook = Rook(self._ctx, self._context, self._echo)
        bucket_name = 'nexus'

        if cluster == self._master_cluster:
            self._create_dbs(Databases(self._ctx, self._context, self._echo), cluster)
            rook.create_bucket(cluster, bucket_name, install, Namespace.sonatype)

        bucket_data = rook.get_s3_login_details(self._master_cluster, cluster, Namespace.sonatype, bucket_name)

        data = {
            'values': {
                'fqdn': get_fqdn('nexus', self._context.secrets, self._context.cluster()),
                'oauth_fqdn': get_fqdn('oauth', self._context.secrets, self._context.cluster()),
                'sonatype': self._context.secrets['sonatype'],
                'db_name': 'nexus'
            }
        }
        data['values'].update(bucket_data)

        ApplicationsCtrl(self._ctx, self._context, self._echo).install_app(
            'sonatype', data, Namespace.sonatype, install)

    def _create_dbs(self, databases: Databases, db_master_cluster: Cluster):
        databases.postgres_create_user(
            db_master_cluster,
            self._context.secrets['sonatype']['db']['user'],
            self._context.secrets['sonatype']['db']['pass'],
        )
        databases.postgres_create_db(
            db_master_cluster,
            nexus_registry
        )
        databases.postgres_grant(
            db_master_cluster,
            nexus_registry,
            self._context.secrets['sonatype']['db']['user']
        )
