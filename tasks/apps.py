import os

from gitea import *
from invoke import task
from tabulate import tabulate

from tasks.controllers.ApplicationsCtrl import ApplicationsCtrl
from tasks.controllers.ConstellationSpecCtrl import ConstellationSpecCtrl
from tasks.dao.SystemContext import SystemContext
from tasks.helpers import get_secrets_dir, get_secret_envs, get_nodes_ips, get_secrets, \
    get_constellation, get_jinja, get_fqdn, get_ccontext, get_ip_addresses_file_path
from tasks.models.ConstellationSpecV01 import VipRole
from tasks.models.Namespaces import Namespace
from tasks.models.ReservedVIPs import ReservedVIPs
from tasks.wrappers.Helm import Helm


@task()
def print_available(ctx, echo: bool = False):
    """
    List compatible applications
    """
    context = SystemContext(ctx, echo)
    app_ctrl = ApplicationsCtrl(ctx, context, echo)

    print(tabulate(
        app_ctrl.get_available(),
        headers=['name', 'path']))


def render_patch(ctx, nodes: list, path_tpl_path, data: dict):
    """
    ToDo: Render jinja style talos patch to ~/.gocy/[constellation]/[cluster]/patch
        Append node information to the rendered file.
    """
    pass


def get_gcp_token_file_name():
    return os.path.join(
        get_secrets_dir(),
        "dns_admin_token.json"
    )


def get_google_dns_token(ctx):
    gcp_token_file_name = get_gcp_token_file_name()
    if os.path.isfile(gcp_token_file_name):
        print("File {} already exists, skipping".format(gcp_token_file_name))
        return

    secrets = get_secret_envs()
    ctx.run("gcloud iam service-accounts keys create {} --iam-account {}@{}.iam.gserviceaccount.com".format(
        get_gcp_token_file_name(),
        secrets['GCP_SA_NAME'],
        secrets['GCP_PROJECT_ID']
    ), echo=True)


@task()
def gcloud_login(ctx):
    """
    If you rae using gcp and your DNS provider, you can use this to log in to the console.
    """
    ctx.run("gcloud auth login", echo=True)


@task()
def deploy_dns_management_token(ctx, provider='google'):
    """
    Creates the DNS token secret to be used by external-dns and cert-manager
    """
    ctx.run('kubectl create namespace {} | true'.format(Namespace.dns_tls), echo=True)

    if provider == 'google':
        get_google_dns_token(ctx)

        ctx.run("kubectl -n {} create secret generic '{}' --from-file=credentials.json={} | true".format(
            Namespace.dns_tls,
            os.environ.get('GCP_SA_NAME'),
            get_gcp_token_file_name()
        ), echo=True)

    else:
        print("Unsupported DNS provider: " + provider)


@task(deploy_dns_management_token)
def dns_tls(ctx, install: bool = False, echo: bool = False):
    """
    Install Helm chart apps/dns-and-tls, apps/dns-and-tls-dependencies
    """
    app_name = 'dns-and-tls'
    secrets = get_secrets()
    data = {
        'values': {
            'admin_email': secrets['env']['GOCY_ADMIN_EMAIL'],
            'project_id': secrets['env']['GCP_PROJECT_ID']
        },
        'deps': {
            'dns-tls': {
                'google_project': secrets['env']['GCP_PROJECT_ID'],
                'domain_filter': secrets['env']['GOCY_DOMAIN']
            }
        }
    }
    ApplicationsCtrl(ctx, SystemContext(ctx, echo), echo).install_app(
        app_name, data, Namespace.dns_tls, install)


@task()
def whoami(ctx, oauth: bool = False, install: bool = False, global_ingress: bool = False, echo: bool = False):
    """
    Install Helm chart apps/whoami
    """
    app_name = 'whoami'
    context = SystemContext(ctx, echo)
    cluster = context.cluster
    secrets = get_secrets()

    if oauth:
        fqdn = get_fqdn('whoami-oauth', secrets, cluster)
    else:
        fqdn = get_fqdn('whoami', secrets, cluster)

    data = {
        'values': {
            'whoami_fqdn': fqdn,
            'name': cluster.name,
            'oauth_enabled': oauth,
            'oauth_fqdn': 'https://' + get_fqdn('oauth', secrets, cluster),
            'ingress_class_name': 'nginx-global' if global_ingress else 'nginx'
        }
    }

    ApplicationsCtrl(ctx, SystemContext(ctx, echo), echo).install_app(
        app_name, data, Namespace.apps, install)


@task()
def argo(ctx, install: bool = False, echo: bool = False):
    """
    Install ArgoCD
    """
    app_name = 'argo'
    context = SystemContext(ctx, echo)
    cluster = context.cluster
    secrets = get_secrets()

    constellation = context.constellation

    data = {
        'values': {
            'constellation_name': constellation.name,
            'bary_name': constellation.bary.name,
            'clusters': list(context.constellation),
            'destination_namespace': Namespace.argocd
        },
        'deps': {
            'argo': {
                'argocd_fqdn': get_fqdn('argo', secrets, cluster),
                'bouncer_fqdn': get_fqdn('bouncer', secrets, cluster),
                'client_secret': secrets['env']['GOCY_ARGOCD_SSO_CLIENT_SECRET'],
                'constellation_name': get_ccontext()
            }
        }
    }

    # ToDo:
    # on satellites:
    # kubectl apply -f https://raw.githubusercontent.com/argoproj/argo-cd/v2.7.3/manifests/crds/application-crd.yaml
    # kubectl create namespace argocd

    ApplicationsCtrl(ctx, context, echo).install_app(
        app_name, data, Namespace.dns_tls, install)


@task()
def argo_add_cluster(ctx, cluster_name: str, echo: bool = False):
    """
    With ArgoCD present on the cluster add connections to other constellation clusters.
    """
    context = SystemContext(ctx, echo)
    constellation_ctrl = ConstellationSpecCtrl(context.project_paths, context.constellation.name)
    cluster = constellation_ctrl.get_cluster_by_name(cluster_name)
    secrets = context.secrets

    argo_admin_pass = ctx.run('kubectl --namespace '
                              + Namespace.argocd.value
                              + ' get secret argocd-initial-admin-secret -o jsonpath="{.data.password}" | base64 -d',
                              hide='stdout', echo=True).stdout

    ctx.run('argocd --grpc-web login --username admin --password {} {}'.format(
        argo_admin_pass,
        get_fqdn('argo', secrets, cluster)
    ), echo=echo)
    ctx.run('argocd --grpc-web cluster add admin@{} --name {}'.format(cluster.name, cluster.name), echo=echo)


@task()
def gitea(ctx, install: bool = False, echo: bool = False):
    """
    Install gitea
    """
    app_name = 'gitea'
    context = SystemContext(ctx, echo)
    cluster = context.cluster
    secrets = context.secrets

    data = {
        'values': {
            'cluster_domain': cluster.name + '.local',
            'gitea_fqdn': get_fqdn('gitea', secrets, cluster),
            'dex_url': get_fqdn('bouncer', secrets, cluster),
        }
    }
    data['values'].update(secrets['gitea'])

    ApplicationsCtrl(ctx, context, echo).install_app(
        app_name, data, Namespace.gitea, install)


@task()
def gitea_port_forward(ctx, echo: bool = False):
    """
    Port forward gitea to localhost. Execute in a separate terminal, prior to apps.gitea-provision.
    """
    ctx.run("kubectl --context=admin@{} --namespace gitea port-forward statefulsets/gitea 3000:3000".format(
        get_constellation().bary.name
    ), echo=echo)


@task(gitea)
def gitea_provision(ctx, ingres_enabled: bool = False, echo: bool = False):
    """
    Provision local gitea, so that it works with Argo
    """
    context = SystemContext(ctx, echo)
    cluster = context.cluster
    secrets = context.secrets

    gitea_fqdn = 'localhost:3000'
    if ingres_enabled:
        gitea_fqdn = get_fqdn('gitea', secrets, cluster)

    data = {
        'cluster_domain': cluster.name + '.local',
        'gitea_fqdn': gitea_fqdn,
        'dex_url': get_fqdn('bouncer', secrets, cluster),
    }
    data.update(secrets['gitea'])

    gitea_client = Gitea(
        "https://" if ingres_enabled else "http://" + data['gitea_fqdn'],
        auth=(
            secrets['gitea']['admin_user'],
            secrets['gitea']['admin_password'])
    )

    admin = gitea_client.get_user()
    print("Gitea Version: " + gitea_client.get_version())
    print("API-Token belongs to user: " + admin.username)

    gitea_client.create_org(admin, 'gocy', "GOCY configuration")
    gocy = Organization.request(gitea_client, 'gocy')

    gocy.commit()
    constellation_name = context.constellation.name

    gocy.create_repo(
        constellation_name,
        'Configuration of {} constellation'.format(constellation_name),
        autoInit=False
    )


@task()
def dbs(ctx, install: bool = False, echo: bool = False):
    """
    Install shared databases
    """
    app_name = 'dbs'
    context = SystemContext(ctx, echo)
    cluster = context.cluster
    secrets = context.secrets

    data = {
        'values': {
            'cluster_domain': cluster.name + '.local',
            'cluster_name': cluster.name,
            'cockroach_fqdn': get_fqdn('cockroach', secrets, cluster),
            'oauth_fqdn': get_fqdn('oauth', secrets, cluster),
        }
    }
    data['values'].update(secrets['dbs'])

    ApplicationsCtrl(ctx, context, echo).install_app(
        app_name, data, Namespace.database, install)


@task()
def dashboards(ctx, install: bool = False, echo: bool = False):
    app_name = 'dashboards'
    context = SystemContext(ctx, echo)
    cluster = context.cluster
    secrets = context.secrets

    data = {
        'values': {
            'k8s_dashboard_fqdn': get_fqdn(['k8s', cluster.name, 'dash'], secrets, cluster),
            'rook_fqdn': get_fqdn(['rook', cluster.name, 'dash'], secrets, cluster),
            'hubble_fqdn': get_fqdn(['hubble', cluster.name, 'dash'], secrets, cluster),
            'oauth_fqdn': get_fqdn('oauth', secrets, cluster),
        }
    }

    ApplicationsCtrl(ctx, context, echo).install_app(
        app_name, data, Namespace.dashboards, install)


@task()
def harbor(ctx, install: bool = False, echo: bool = False):
    app_name = 'harbor'
    context = SystemContext(ctx, echo)
    cluster = context.cluster
    secrets = context.secrets

    data = {
        'values': {
            'harbor_fqdn': get_fqdn('harbor', secrets, cluster)
        }
    }
    data['values'].update(secrets['harbor'])

    ApplicationsCtrl(ctx, context, echo).install_app(
        app_name, data, Namespace.apps, install)


@task()
def observability(ctx, install: bool = False, echo: bool = False):
    app_name = 'observability'
    context = SystemContext(ctx, echo)
    cluster = context.cluster
    secrets = context.secrets

    data = {
        'values': {
            'jaeger_fqdn': get_fqdn('jaeger', secrets, cluster),
            'oauth_fqdn': get_fqdn('oauth', secrets, cluster),
            'grafana_fqdn': get_fqdn('grafana', secrets, cluster),
            'cluster_name': cluster.name + '.local'
        }
    }
    data['values'].update(secrets['grafana'])

    ApplicationsCtrl(ctx, context, echo).install_app(
        app_name, data, Namespace.observability, install)


@task()
def ingress(ctx, install: bool = False, echo: bool = False):
    """
    Install Helm chart apps/ingress-bundle
    """
    app_name = 'ingress'
    context = SystemContext(ctx, echo)
    cluster = context.cluster

    apps_ctrl = ApplicationsCtrl(ctx, context, echo)

    with open(get_ip_addresses_file_path(cluster, VipRole.ingress)) as ip_addresses_file:
        ingress_vips = ReservedVIPs().parse_raw(ip_addresses_file.read())

    data = {
        'values': {
            'address_pool_name': 'ingress-public-ipv4',
            'ingress_class_name': 'nginx',
            'ingress_class_default': True
        }
    }

    apps_ctrl.install_app(app_name, data, Namespace.ingress, install)

    if len(ingress_vips.global_ipv4) > 0:
        data = {
            'values': {
                'address_pool_name': 'ingress-global-ipv4',
                'ingress_class_name': 'nginx-global',
                'ingress_class_default': False
            }
        }
        values_file = apps_ctrl.render_values(
            app_name + '-global',
            data,
            namespace=app_name,
            app_dir_name=app_name,
            target_app_suffix="global"
        )
        helm = Helm(ctx, echo)
        helm.install(values_file, app_name + '-global', namespace=app_name, install=install)


@task()
def storage(ctx, install: bool = False, echo: bool = False):
    """
    Install storage
    """
    app_name = 'storage'
    context = SystemContext(ctx, echo)

    data = {
        'values': {
            'operator_namespace': app_name
        },
        'deps': {
            'rook': {}
        }
    }

    ApplicationsCtrl(ctx, context, echo).install_app(
        app_name, data, Namespace.storage, install)


def idp_auth_chart(apps_ctrl: ApplicationsCtrl, app_name, data: dict, install: bool):
    apps_ctrl.install_app(app_name, data, app_name, install)


def idp_auth_kubelogin_chart(apps_ctrl: ApplicationsCtrl, namespace: Namespace, data: dict, install: bool):
    app_name = 'idp-auth-kubelogin'
    apps_ctrl.install_app(app_name, data=data, namespace=namespace, install=install)


@task()
def idp_auth(ctx, install: bool = False, echo: bool = False):
    """
    Produces ${HOME}/.gocy/[constellation_name]/[cluster_name]/idp-auth-values.yaml
    Uses it to install idp-auth. IDP should be installed on bary cluster only.
    """
    app_name = 'idp-auth'
    context = SystemContext(ctx, echo)
    cluster = context.cluster
    secrets = context.secrets
    jinja = get_jinja()
    constellation = context.constellation
    apps_ctrl = ApplicationsCtrl(ctx, context, echo)

    data = {
        'values': {
            'bouncer_fqdn': get_fqdn('bouncer', secrets, cluster),
            'oauth_fqdn': get_fqdn('oauth', secrets, cluster),
            'argo_fqdn': get_fqdn('argo', secrets, cluster),
            'gitea_fqdn': get_fqdn('gitea', secrets, cluster)
        }
    }
    data['values'].update(secrets)

    if cluster.name == constellation.bary.name:
        idp_auth_chart(apps_ctrl, app_name, data, install)

    idp_auth_kubelogin_chart(apps_ctrl, Namespace.idp_auth, data, install)

    with open(os.path.join(
            'templates',
            'patch',
            'oidc',
            'control-plane.jinja.yaml')) as talos_oidc_patch_file:
        talos_oidc_patch_tpl = jinja.from_string(talos_oidc_patch_file.read())

    talos_oidc_patch = talos_oidc_patch_tpl.render(data['values'])
    talos_oidc_patch_dir = os.path.join(get_secrets_dir(), 'patch', 'oidc')

    ctx.run("mkdir -p " + talos_oidc_patch_dir, echo=echo)
    talos_oidc_patch_file_path = os.path.join(talos_oidc_patch_dir, 'talos_oidc_patch.yaml')
    with open(talos_oidc_patch_file_path, 'w') as talos_oidc_patch_file:
        talos_oidc_patch_file.write(talos_oidc_patch)

    cluster_nodes = get_nodes_ips(ctx)
    ctx.run("talosctl --nodes {} patch mc -p @{}".format(
        ",".join(cluster_nodes.control_plane),
        talos_oidc_patch_file_path
    ), echo=echo)


@task()
def network_dependencies(ctx, install: bool = False, echo: bool = False):
    """
    Deploy chart apps/network-services-dependencies containing Cilium and MetalLB
    """
    app_name = 'network-dependencies'

    context = SystemContext(ctx, echo)
    app_ctrl = ApplicationsCtrl(ctx, context, echo)

    values_file = app_ctrl.prepare_network_dependencies(app_name, Namespace.network_services)

    if install:
        helm = Helm(ctx, echo)
        helm.install(values_file, app_name, install, Namespace.network_services)


@task()
def network_services(ctx, install: bool = False, echo: bool = False):
    """
    Deploys apps/network-services chart, with BGP VIP pool configuration, based on
    VIPs registered in EquinixMetal. As of now the assumption is 1 GlobalIPv4 for ingress,
    1 PublicIPv4 for Cilium Mesh API server.
    """

    app_name = 'network-services'
    context = SystemContext(ctx, echo)
    cluster = context.cluster

    data = {
        'values': {
            'cluster_name': cluster.name,
            'vips': {
                str(VipRole.mesh): dict(),
                str(VipRole.ingress): dict()
            }
        }
    }

    for role in data['values']['vips']:
        with open(context.project_paths.vips_file_by_role(role)) as ip_addresses_file:
            data['values']['vips'][role] = ReservedVIPs().parse_raw(ip_addresses_file.read()).dict()

    ApplicationsCtrl(ctx, context, echo).install_app(
        app_name, data, Namespace.network_services, install)
