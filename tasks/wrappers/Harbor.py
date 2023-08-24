from typing import Callable

import harbor_client
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

    def __init__(self, ctx: Context, context: SystemContext, echo: bool, cluster: Cluster = None):
        self._ctx = ctx
        self._context = context
        self._satellites = context.constellation.satellites
        self._echo = echo

        if cluster is not None:
            self._satellites = [cluster]

    def install(self, install: bool, application_directory='harbor'):
        # self._configure_db(Databases(self._ctx, self._context, self._echo))

        secrets = self._context.secrets
        context = self._context.cluster()
        for cluster in self._satellites:
            self._context.set_cluster(cluster)
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
                    'db_harbor_notary_signer': harbor_notary_signer
                }
            }

            ApplicationsCtrl(self._ctx, self._context, self._echo).install_app(
                application_directory, data, Namespace.apps, install)

        self._context.cluster(context.name)

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
