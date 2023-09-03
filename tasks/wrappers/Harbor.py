import base64
from typing import Callable

import harbor_client
import yaml
from harbor_client import Configuration, ProjectReq
from invoke import Context

from tasks.controllers.ApplicationsCtrl import ApplicationsCtrl
from tasks.dao.SystemContext import SystemContext
from tasks.helpers import get_fqdn
from tasks.models.ConstellationSpecV01 import Cluster
from tasks.models.Namespaces import Namespace
from tasks.wrappers.Databases import Databases

harbor_registry = 'harbor_registry'
harbor_notary_server = 'harbor_notary_server'
harbor_notary_signer = 'harbor_notary_signer'


def _create_project(client_config: Configuration, cluster: Cluster, **kwargs):
    project_api = harbor_client.ProjectApi(harbor_client.ApiClient(client_config))
    project_req = ProjectReq()
    project_req.project_name = kwargs['project_name']
    project_req.public = False
    project_api.create_project(project_req)


class Harbor:
    _ctx: Context
    _context: SystemContext
    _satellites: list[Cluster]
    _cluster: Cluster

    def __init__(self, ctx: Context, context: SystemContext, echo: bool, cluster_name: str = None):
        self._ctx = ctx
        self._context = context
        self._satellites = context.constellation.satellites
        self._echo = echo

        if cluster_name is not None:
            self._satellites = [self._context.cluster(cluster_name)]

    def install_storage(self, install: bool, application_directory="harbor-storage"):
        context = self._context.cluster()

        for cluster in self._satellites:
            self._context.set_cluster(cluster)

            data = {
                'values': {
                    'object_store_name': 'm-{}-harbor'.format(cluster.name)
                }
            }

            ApplicationsCtrl(self._ctx, self._context, self._echo).install_app(
                application_directory, data, Namespace.apps, install)

        self._context.set_cluster(context)

    def _get_s3_login_details(self, master_cluster: Cluster, cluster: Cluster) -> dict:
        object_bucket_yaml = self._ctx.run(
            "kubectl --context admin@{} "
            "--namespace {} get ObjectBuckets obc-harbor-harbor-bucket -o yaml".format(
                master_cluster.name,
                Namespace.harbor
            ), hide="stdout", echo=self._echo).stdout
        object_bucket = dict(yaml.safe_load(object_bucket_yaml))

        bucket_secret_yaml = self._ctx.run(
            "kubectl --context admin@{} --namespace {} get secrets harbor-bucket -o yaml".format(
                master_cluster.name,
                Namespace.harbor
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

        return {
            'bucket': object_bucket['spec']['endpoint']['bucketName'],
            'accesskey': base64.b64decode(str.encode(bucket_secret['data']['AWS_ACCESS_KEY_ID'])).decode('utf-8'),
            "secretkey": base64.b64decode(str.encode(bucket_secret['data']['AWS_SECRET_ACCESS_KEY'])).decode('utf-8'),
            "regionendpoint": regionendpoint
        }

    def install(self, install: bool, application_directory='harbor'):
        secrets = self._context.secrets
        context = self._context.cluster()
        master_cluster = self._context.constellation.satellites[0]

        for cluster in self._satellites:
            self._context.set_cluster(cluster)
            if cluster == master_cluster:
                self._configure_db(Databases(self._ctx, self._context, self._echo))  # ToDo: DB detection

            data = {
                'values': {
                    'global_fqdn': get_fqdn('harbor', secrets, cluster),
                    'local_fqdn': get_fqdn(['harbor', cluster.name], secrets, cluster),
                    'harbor': secrets['harbor'],
                    'db_host': 'postgres-{}-rw.{}'.format(
                        self._context.constellation.satellites[0].name,
                        Namespace.database
                    ),
                    'db_port': '5432',
                    'db_harbor_registry': harbor_registry,
                    'db_harbor_notary_server': harbor_notary_server,
                    'db_harbor_notary_signer': harbor_notary_signer,
                    'region': ""
                }
            }

            data['values'].update(self._get_s3_login_details(master_cluster, cluster))

            ApplicationsCtrl(self._ctx, self._context, self._echo).install_app(
                application_directory, data, Namespace.apps, install)

        self._context.set_cluster(context)

    def uninstall(self):
        context = self._context.cluster()
        for cluster in self._satellites:
            self._context.set_cluster(cluster)
            self._ctx.run("helm uninstall --namespace {} {}".format(
                'harbor',
                'harbor'
            ), echo=self._echo)

        self._context.cluster(context.name)

    def _configure_db(self, databases: Databases, db_master_cluster: Cluster = None):
        context = self._context.cluster()
        if db_master_cluster is None:
            db_master_cluster = self._context.constellation.satellites[0]

        self._context.cluster(db_master_cluster.name)

        databases.postgres_create_user(
            db_master_cluster,
            self._context.secrets['harbor']['db']['user'],
            self._context.secrets['harbor']['db']['pass'],
        )
        databases.postgres_create_db(
            db_master_cluster,
            harbor_registry
        )
        databases.postgres_create_db(
            db_master_cluster,
            harbor_notary_server
        )
        databases.postgres_create_db(
            db_master_cluster,
            harbor_notary_signer
        )
        databases.postgres_grant(
            db_master_cluster,
            harbor_registry,
            self._context.secrets['harbor']['db']['user']
        )
        databases.postgres_grant(
            db_master_cluster,
            harbor_notary_server,
            self._context.secrets['harbor']['db']['user']
        )
        databases.postgres_grant(
            db_master_cluster,
            harbor_notary_signer,
            self._context.secrets['harbor']['db']['user']
        )

        self._context.cluster(context.name)
        
    def _for_client_config(self, action: Callable, **kwargs):
        client_config = harbor_client.Configuration()
        client_config.username = self._context.secrets['harbor']['admin_user']
        client_config.password = self._context.secrets['harbor']['admin_pass']
        for cluster in self._satellites:
            client_config.host = "https://{}/api/v2.0".format(
                get_fqdn(
                    ['harbor', cluster.name],
                    self._context.secrets,
                    cluster
                ))
            action(client_config, cluster, **kwargs)

    def _oidc_enable(self, client_config: Configuration, cluster: Cluster):
        """
        OAUTH becomes the default auth mode.
        Login via DB possible via /account/sign-in
        """
        config_api = harbor_client.ConfigureApi(harbor_client.ApiClient(client_config))
        config = harbor_client.Configurations()

        config.oidc_client_secret = self._context.secrets['harbor']['dex_client_secret']
        config.auth_mode = 'oidc_auth'
        config.primary_auth_mode = True
        config.oidc_admin_group = self._context.secrets['harbor']['oidc_admin_group']
        config.oidc_auto_onboard = True
        config.oidc_client_id = 'harbor'
        config.oidc_endpoint = "https://{}".format(get_fqdn('bouncer', self._context.secrets, cluster))
        config.oidc_groups_claim = 'groups'
        config.oidc_name = 'dex'
        config.oidc_scope = 'openid,email,groups,profile,offline_access'
        config.oidc_user_claim = 'email'
        config.oidc_verify_cert = True

        config.project_creation_restriction = 'adminonly'

        config_api.update_configurations(config)

    def oidc_enable(self):
        self._for_client_config(self._oidc_enable)

    def create_project(self, project_name: str):
        self._for_client_config(_create_project, project_name=project_name)
