import base64
import logging

import yaml
from invoke import Context, Failure

from tasks.controllers.ApplicationsCtrl import ApplicationsCtrl
from tasks.dao.SystemContext import SystemContext
from tasks.helpers import get_fqdn
from tasks.models.ConstellationSpecV01 import Cluster
from tasks.models.Namespaces import Namespace
from tasks.wrappers.Databases import Databases
from tasks.wrappers.Rook import Rook

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
        storage:
        https://jfrog.com/help/r/jfrog-installation-setup-documentation/s3-sharding-examples
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
            self._create_dbs(Databases(self._ctx, self._context, self._echo), cluster)
            rook = Rook(self._ctx, self._context, self._echo)
            rook.create_bucket(cluster, 'artifactory', install)

        # self._create_db_secret()
        self._install_enterprise(cluster, install)

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
        data['deps']['20_artifactory'].update(
            self._get_s3_login_details(
                self._master_cluster, cluster, Namespace.jfrog))
        ApplicationsCtrl(self._ctx, self._context, self._echo).install_app(
            self._application_directory, data, Namespace.jfrog, install)

    def _get_s3_login_details(self, master_cluster: Cluster, cluster: Cluster, namespace: Namespace) -> dict:
        object_bucket_yaml = self._ctx.run(
            "kubectl --context admin@{} "
            "--namespace {} get ObjectBuckets obc-jfrog-artifactory-bucket -o yaml".format(
                master_cluster.name,
                namespace
            ), hide="stdout", echo=self._echo).stdout
        object_bucket = dict(yaml.safe_load(object_bucket_yaml))

        bucket_secret_yaml = self._ctx.run(
            "kubectl --context admin@{} --namespace {} get secrets artifactory-bucket -o yaml".format(
                master_cluster.name,
                namespace
            ), hide="stdout", echo=self._echo).stdout
        bucket_secret = dict(yaml.safe_load(bucket_secret_yaml))

        """
        In our Object Store Multisite, objects are replicated across the zone. This means it is sufficient to create
        the bucket once in one cluster. The ceph will automagically sync it across.
        This mean that in all other clusters we wish to use this bucket we need to fetch the bucket details
        from the master cluster. Then on all other clusters just replace the endpoint url, so that it points to the 
        local rook/ceph service.
        """
        regionendpoint = "http://{}".format(object_bucket['spec']['endpoint']['bucketHost'])
        if master_cluster != cluster:
            regionendpoint = regionendpoint.replace(master_cluster.name, cluster.name)
        # regionendpoint = "http://rgw-proxy.storage.svc:8080"

        return {
            'bucket': object_bucket['spec']['endpoint']['bucketName'],
            'accesskey': base64.b64decode(str.encode(bucket_secret['data']['AWS_ACCESS_KEY_ID'])).decode('utf-8'),
            "secretkey": base64.b64decode(str.encode(bucket_secret['data']['AWS_SECRET_ACCESS_KEY'])).decode('utf-8'),
            "regionendpoint": regionendpoint
        }

    def uninstall(self):
        try:
            self._ctx.run("helm uninstall --namespace {} {}".format(Namespace.jfrog, 'artifactory'), echo=self._echo)
        except Failure:
            logging.info('Most likely already gone...')
