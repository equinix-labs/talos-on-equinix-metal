from gitea import *
from invoke import task
from tabulate import tabulate

from tasks.controllers.ApplicationsCtrl import ApplicationsCtrl
from tasks.controllers.ConstellationSpecCtrl import ConstellationSpecCtrl
from tasks.controllers.DNSCtrl import DNSProvider, DNSCtrl
from tasks.dao.ProjectPaths import RepoPaths
from tasks.dao.SystemContext import SystemContext
from tasks.helpers import get_fqdn
from tasks.models.ConstellationSpecV01 import VipRole
from tasks.models.Namespaces import Namespace
from tasks.models.ReservedVIPs import ReservedVIPs
from tasks.wrappers.CockroachDB import CockroachDB
from tasks.wrappers.Harbor import Harbor
from tasks.wrappers.Helm import Helm
from tasks.wrappers.JFrog import JFrog
from tasks.wrappers.JinjaWrapper import JinjaWrapper
from tasks.wrappers.Kubectl import Kubectl
from tasks.wrappers.Talos import Talos


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


@task()
def dns_tls_token(ctx, provider: DNSProvider = DNSProvider.gcp, echo: bool = False):
    """
    Creates the DNS token secret to be used by external-dns and cert-manager
    """
    context = SystemContext(ctx, echo)
    dns_ctrl = DNSCtrl(ctx, context, echo)
    dns_ctrl.create_secret(provider)


@task(dns_tls_token)
def dns_tls(ctx, install: bool = False, echo: bool = False):
    """
    Install Helm chart apps/dns-and-tls, apps/dns-and-tls-dependencies
    """
    application_directory = 'dns-and-tls'
    context = SystemContext(ctx, echo)
    secrets = context.secrets

    ca_secret_name = '{}-ca-issuer'.format(context.constellation.name)

    data = {
        'values': {
            'admin_email': secrets['env']['GOCY_ADMIN_EMAIL'],
            'project_id': secrets['env']['GCP_PROJECT_ID'],
            'ca_secret_name': ca_secret_name
        },
        'deps': {
            'cert_manager': {
                'google_project': secrets['env']['GCP_PROJECT_ID'],
                'domain_filter': secrets['env']['GOCY_DOMAIN'],
                'namespace': Namespace.dns_tls
            }
        }
    }

    kubectl = Kubectl(ctx, context, echo)
    kubectl.create_tls_secret(
        ca_secret_name, Namespace.dns_tls, context.project_paths.ca_crt_file(), context.project_paths.ca_key_file())

    ApplicationsCtrl(ctx, SystemContext(ctx, echo), echo).install_app(
        application_directory, data, Namespace.dns_tls, install)


@task()
def whoami(ctx, oauth: bool = False, install: bool = False, global_ingress: bool = False, echo: bool = False):
    """
    Install Helm chart apps/whoami
    """
    application_directory = 'whoami'
    context = SystemContext(ctx, echo)
    cluster = context.cluster()
    secrets = context.secrets

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
        application_directory, data, Namespace.apps, install)


@task()
def argo(ctx, install: bool = False, echo: bool = False):
    """
    Install ArgoCD
    """
    application_directory = 'argo'
    context = SystemContext(ctx, echo)
    cluster = context.cluster()
    secrets = context.secrets

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
                'constellation_name': context.constellation.name
            }
        }
    }

    # ToDo:
    # on satellites:
    # kubectl apply -f https://raw.githubusercontent.com/argoproj/argo-cd/v2.7.3/manifests/crds/application-crd.yaml
    # kubectl create namespace argocd

    ApplicationsCtrl(ctx, context, echo).install_app(
        application_directory, data, Namespace.dns_tls, install)


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
    application_directory = 'gitea'
    context = SystemContext(ctx, echo)
    cluster = context.cluster()
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
        application_directory, data, Namespace.gitea, install)


@task()
def gitea_port_forward(ctx, echo: bool = False):
    """
    Port forward gitea to localhost. Execute in a separate terminal, prior to apps.gitea-provision.
    """
    context = SystemContext(ctx, echo)

    ctx.run("kubectl --context=admin@{} --namespace gitea port-forward statefulsets/gitea 3000:3000".format(
        context.constellation.bary.name
    ), echo=echo)


@task(gitea)
def gitea_provision(ctx, ingres_enabled: bool = False, echo: bool = False):
    """
    Provision local gitea, so that it works with Argo
    """
    context = SystemContext(ctx, echo)
    cluster = context.cluster()
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
def dbs_install(ctx, install: bool = False, echo: bool = False):
    """
    Install shared databases
    """
    context = SystemContext(ctx, echo)

    cockroach = CockroachDB(ctx, context, echo)
    cockroach.install(install)


@task()
def dbs_port_forward_ui(ctx, cluster_name: str, echo: bool = True):
    """
    Forward UI
    """
    context = SystemContext(ctx, echo)

    cockroach = CockroachDB(ctx, context, echo)
    cockroach.port_forward_ui(cluster_name)


@task()
def dbs_port_forward_db(ctx, cluster_name: str, echo: bool = True):
    """
    Forward DB
    https://www.cockroachlabs.com/docs/v23.1/dbeaver
    """
    context = SystemContext(ctx, echo)

    cockroach = CockroachDB(ctx, context, echo)
    cockroach.port_forward_db(cluster_name)


@task()
def dbs_uninstall(ctx, echo: bool = True):
    """
    Uninstall shared databases
    """
    context = SystemContext(ctx, echo)

    cockroach = CockroachDB(ctx, context, echo)
    cockroach.uninstall()


@task()
def jfrog_artifactory_install(ctx, install: bool = False, echo: bool = False):
    """
    Uninstall shared databases
    """
    context = SystemContext(ctx, echo)

    jfrog = JFrog(ctx, context, echo)
    jfrog.install(install)


@task()
def dashboards(ctx, install: bool = False, echo: bool = False):
    application_directory = 'dashboards'
    context = SystemContext(ctx, echo)
    cluster = context.cluster()
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
        application_directory, data, Namespace.dashboards, install)


@task()
def harbor(ctx, install: bool = False, echo: bool = False):
    application_directory = 'harbor'
    context = SystemContext(ctx, echo)
    cluster = context.cluster()
    secrets = context.secrets

    data = {
        'values': {
            'global_fqdn': get_fqdn('harbor', secrets, cluster),
            'local_fqdn': get_fqdn(['harbor', cluster.name], secrets, cluster)
        }
    }
    data['values'].update(secrets['harbor'])

    ApplicationsCtrl(ctx, context, echo).install_app(
        application_directory, data, Namespace.apps, install)


@task()
def observability(ctx, install: bool = False, echo: bool = False):
    """
    Install observability helm chart
    """
    application_directory = 'observability'
    context = SystemContext(ctx, echo)
    cluster = context.cluster()
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
        application_directory, data, Namespace.observability, install)


@task()
def istio(ctx, install: bool = False, echo: bool = False):
    """
    Install istio
    """
    application_directory = 'istio'
    context = SystemContext(ctx, echo)
    cluster = context.cluster()

    apps_ctrl = ApplicationsCtrl(ctx, context, echo)

    with open(context.project_paths.vips_file_by_role(VipRole.ingress)) as ip_addresses_file:
        ingress_vips = ReservedVIPs().parse_raw(ip_addresses_file.read())

    data = {
        'values': {},
        'deps': {
            '01-crds': {},
            '02-istiod': {},
            '03-gateway': {}
        }
    }

    apps_ctrl.install_app(application_directory, data, Namespace.istio, install)


@task()
def nginx(ctx, install: bool = False, echo: bool = False):
    """
    Install Helm chart apps/ingress-bundle
    """
    application_directory = 'nginx'
    context = SystemContext(ctx, echo)
    cluster = context.cluster()

    apps_ctrl = ApplicationsCtrl(ctx, context, echo)

    with open(context.project_paths.vips_file_by_role(VipRole.ingress)) as ip_addresses_file:
        ingress_vips = ReservedVIPs().parse_raw(ip_addresses_file.read())

    data = {
        'values': {
            'address_pool_name': 'ingress-public-ipv4',
            'ingress_class_name': 'nginx',
            'ingress_class_default': True
        }
    }

    apps_ctrl.install_app(application_directory, data, Namespace.nginx, install)

    if len(ingress_vips.global_ipv4) > 0:
        data = {
            'values': {
                'address_pool_name': 'ingress-global-ipv4',
                'ingress_class_name': 'nginx-global',
                'ingress_class_default': False
            }
        }
        values_file = apps_ctrl.render_values(
            application_directory,
            data,
            namespace=Namespace.nginx,
            application_name=application_directory + '-global',
            target_app_suffix="global"
        )
        helm = Helm(ctx, echo)
        helm.install(values_file, install, Namespace.nginx)


@task()
def storage(ctx, install: bool = False, echo: bool = False):
    """
    Install storage
    """
    application_directory = 'storage'
    context = SystemContext(ctx, echo)

    data = {
        'values': {
            'operator_namespace': application_directory
        },
        'deps': {
            'rook': {}
        }
    }

    ApplicationsCtrl(ctx, context, echo).install_app(
        application_directory, data, Namespace.storage, install)


@task()
def idp_auth(ctx, install: bool = False, echo: bool = False):
    """
    ToDo
    """
    application_directory = 'idp-auth'
    context = SystemContext(ctx, echo)
    cluster = context.cluster()
    secrets = context.secrets
    jinja = JinjaWrapper()
    constellation = context.constellation
    apps_ctrl = ApplicationsCtrl(ctx, context, echo)

    data = {
        'values': {
            'bouncer_fqdn': get_fqdn('bouncer', secrets, cluster),
            'oauth_fqdn': get_fqdn('oauth', secrets, cluster),
            'argo_fqdn': get_fqdn('argo', secrets, cluster),
            'gitea_fqdn': get_fqdn('gitea', secrets, cluster),
            'harbor_fqdn': get_fqdn('harbor', secrets, cluster),
        }
    }
    data['values'].update(secrets)

    if cluster.name == constellation.bary.name:
        apps_ctrl.install_app(application_directory, data, Namespace.idp_auth, install)

    apps_ctrl.install_app('idp-auth-kubelogin', data, Namespace.idp_auth, install)
    repo_paths = RepoPaths()
    repo_paths.oidc_template_file()

    target = context.project_paths.patch_oidc_file('talos_oidc_patch.yaml')

    jinja.render(repo_paths.oidc_control_plane_template_file(), target, data['values'])

    talos = Talos(ctx, context, cluster, echo)
    talos.patch_endpoints(target)


@task()
def network_multitool(ctx, install: bool = False, echo: bool = False, host_network: bool = False):
    application_directory = 'network-multitool'
    context = SystemContext(ctx, echo)

    data = {
        'values': {
            'host_network': host_network
        }
    }

    ApplicationsCtrl(ctx, context, echo).install_app(
        application_directory, data, Namespace.network_services, install, wait=True)


@task()
def network_dependencies(ctx, install: bool = False, echo: bool = False):
    """
    Deploy chart apps/network-services-dependencies containing Cilium and MetalLB
    """
    application_directory = 'network-dependencies'

    context = SystemContext(ctx, echo)
    app_ctrl = ApplicationsCtrl(ctx, context, echo)

    values_file = app_ctrl.prepare_network_dependencies(application_directory, Namespace.network_services)

    helm = Helm(ctx, echo)
    helm.install(values_file, install, Namespace.network_services)


@task()
def network_services(ctx, install: bool = False, echo: bool = False):
    """
    Deploys apps/network-services chart, with BGP VIP pool configuration, based on
    VIPs registered in EquinixMetal. As of now the assumption is 1 GlobalIPv4 for ingress,
    1 PublicIPv4 for Cilium Mesh API server.
    """

    application_directory = 'network-services'
    context = SystemContext(ctx, echo)
    cluster = context.cluster()

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
        application_directory, data, Namespace.network_services, install)
