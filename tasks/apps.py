import os
from glob import glob
from shutil import copytree, ignore_patterns

import yaml
from gitea import *
from invoke import task
from tabulate import tabulate

from tasks.ReservedVIPs import ReservedVIPs
from tasks.constellation_v01 import Cluster, VipRole
from tasks.helpers import get_secrets_dir, get_cluster_spec_from_context, get_secret_envs, get_nodes_ips, get_secrets, \
    get_constellation, get_jinja, get_fqdn, get_cluster_secrets_dir, get_ccontext, get_ip_addresses_file_path, \
    get_constellation_clusters, get_cluster_spec


def render_values_file(ctx, source: str, target: str, data: dict):
    jinja = get_jinja()
    # ctx.run('mkdir -p ' + str(Path(target).parent.absolute()))
    with open(source) as source_file:
        template = jinja.from_string(source_file.read())

    with open(target, 'w') as target_file:
        rendered_list = [line for line in template.render(data).splitlines() if len(line.rstrip()) > 0]
        target_file.write(os.linesep.join(rendered_list))


def render_values(ctx, cluster: Cluster, app_name, data,
                  namespace,
                  apps_dir_name='apps',
                  app_dir_name=None,
                  target_app_suffix=None,
                  template_file_name='values.jinja.yaml',
                  target_file_name='values.yaml') -> dict:
    """
    Renders jinja style helm values templates to ~/.gocy/[constellation]/[cluster]/apps to be picked up by Argo.
    """
    if app_dir_name is None:
        app_dir_name = app_name

    source_apps_path = os.path.join(apps_dir_name, app_dir_name)
    target_apps_path = os.path.join(
        get_cluster_secrets_dir(cluster),
        os.path.join(
            apps_dir_name,
            app_dir_name if not target_app_suffix else app_dir_name + "-" + target_app_suffix
        )
    )
    os.makedirs(target_apps_path, exist_ok=True)
    copytree(source_apps_path, target_apps_path,
             ignore=ignore_patterns(template_file_name, 'charts'), dirs_exist_ok=True)

    target = os.path.join(target_apps_path, target_file_name)
    template_paths = glob(os.path.join(source_apps_path, '**', template_file_name), recursive=True)

    render_values_file(ctx,
                       os.path.join(source_apps_path, template_file_name),
                       target,
                       data['values'])

    render_values_file(
        ctx,
        os.path.join('templates', 'argo', 'application.jinja.yaml'),
        os.path.join(get_cluster_secrets_dir(cluster), 'argo', 'apps', app_dir_name + '.yaml'),
        {
            'name': app_name,
            'namespace': 'argo-apps',
            'destination': cluster.name,
            'target_namespace': namespace,
            'project': cluster.name,
            'path': os.path.join(cluster.name, 'apps', app_dir_name),
            'repo_url': "http://gitea-http.gitea:3000/gocy/saturn.git"
        }
    )

    targets = {
        'apps': list(),
        'deps': list()
    }
    targets['apps'].append(target)

    if 'deps' not in data:
        return targets

    for template_path in template_paths:
        for dependency_name, dependency_data in data['deps'].items():
            dependency_folder_path = os.path.join('deps', dependency_name)
            if dependency_folder_path in template_path:
                source = os.path.join(
                    source_apps_path,
                    dependency_folder_path,
                    template_file_name
                )
                target = os.path.join(
                    target_apps_path,
                    dependency_folder_path,
                    target_file_name)

                render_values_file(ctx,
                                   source,
                                   target,
                                   dependency_data)

                targets['deps'].append(target)

    return targets


def get_available(ctx, apps_dir='apps', template_file_name='values.jinja.yaml'):
    apps_dirs = glob(os.path.join(apps_dir, '*'), recursive=True)

    compatible_apps = []
    for apps_dir in apps_dirs:
        if os.path.isfile(os.path.join(apps_dir, template_file_name)):
            compatible_apps.append([
                os.path.basename(apps_dir),
                apps_dir
            ])

    return compatible_apps


@task()
def print_available(ctx, apps_dir='apps', template_file_name='values.jinja.yaml'):
    """
    List compatible applications
    """
    print(tabulate(
        get_available(ctx, apps_dir, template_file_name),
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


def get_dns_tls_namespace_name():
    return 'dns-and-tls'


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
    ctx.run('kubectl create namespace {} | true'.format(get_dns_tls_namespace_name()), echo=True)

    if provider == 'google':
        get_google_dns_token(ctx)

        ctx.run("kubectl -n {} create secret generic '{}' --from-file=credentials.json={} | true".format(
            get_dns_tls_namespace_name(),
            os.environ.get('GCP_SA_NAME'),
            get_gcp_token_file_name()
        ), echo=True)

    else:
        print("Unsupported DNS provider: " + provider)


def install_app(ctx, app_name: str, cluster: Cluster, data: dict, namespace: str, install: bool):
    value_files = render_values(ctx, cluster, app_name, data, namespace=namespace)
    helm_install(ctx, value_files, app_name, namespace=namespace, install=install)


@task(deploy_dns_management_token)
def dns_tls(ctx, install: bool = False):
    """
    Install Helm chart apps/dns-and-tls, apps/dns-and-tls-dependencies
    """
    app_name = 'dns-and-tls'
    cluster_spec = get_cluster_spec_from_context(ctx)
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
    install_app(ctx, app_name, cluster_spec, data, get_dns_tls_namespace_name(), install)


@task()
def whoami(ctx, oauth: bool = False, install: bool = False, global_ingress: bool = False):
    """
    Install Helm chart apps/whoami
    """
    app_name = 'whoami'
    cluster_spec = get_cluster_spec_from_context(ctx)
    secrets = get_secrets()

    if oauth:
        fqdn = get_fqdn('whoami-oauth', secrets, cluster_spec)
    else:
        fqdn = get_fqdn('whoami', secrets, cluster_spec)

    data = {
        'values': {
            'whoami_fqdn': fqdn,
            'name': cluster_spec.name,
            'oauth_enabled': oauth,
            'oauth_fqdn': 'https://' + get_fqdn('oauth', secrets, cluster_spec),
            'ingress_class_name': 'nginx-global' if global_ingress else 'nginx'
        }
    }

    install_app(ctx, app_name, cluster_spec, data, app_name, install)


@task()
def argo(ctx, install: bool = False):
    """
    Install ArgoCD
    """
    app_name = 'argo'
    cluster_spec = get_cluster_spec_from_context(ctx)
    secrets = get_secrets()

    constellation = get_constellation()
    clusters = get_constellation_clusters(constellation)

    data = {
        'values': {
            'constellation_name': constellation.name,
            'bary_name': constellation.bary.name,
            'clusters': clusters
        },
        'deps': {
            'argo': {
                'argocd_fqdn': get_fqdn('argo', secrets, cluster_spec),
                'bouncer_fqdn': get_fqdn('bouncer', secrets, cluster_spec),
                'client_secret': secrets['env']['GOCY_ARGOCD_SSO_CLIENT_SECRET'],
                'constellation_name': get_ccontext()
            }
        }
    }

    # ToDo:
    # on satellites:
    # kubectl apply -f https://raw.githubusercontent.com/argoproj/argo-cd/v2.7.3/manifests/crds/application-crd.yaml
    # kubectl create namespace argo-apps

    install_app(ctx, app_name, cluster_spec, data, 'argocd', install)


@task()
def argo_add_cluster(ctx, name, argocd_namespace='argocd'):
    """
    With ArgoCD present on the cluster add connections to other constellation clusters.
    """
    cluster_spec = get_cluster_spec(ctx, name)
    secrets = get_secrets()

    argo_admin_pass = ctx.run('kubectl --namespace '
                              + argocd_namespace
                              + ' get secret argocd-initial-admin-secret -o jsonpath="{.data.password}" | base64 -d',
                              hide='stdout', echo=True).stdout

    ctx.run('argocd --grpc-web login --username admin --password {} {}'.format(
        argo_admin_pass,
        get_fqdn('argo', secrets, cluster_spec)
    ), echo=False)
    ctx.run('argocd --grpc-web cluster add admin@{} --name {}'.format(cluster_spec.name, cluster_spec.name), echo=True)


@task()
def gitea(ctx, install: bool = False):
    """
    Install gitea
    """
    app_name = 'gitea'
    cluster_spec = get_cluster_spec_from_context(ctx)
    secrets = get_secrets()

    data = {
        'values': {
            'cluster_domain': cluster_spec.name + '.local',
            'gitea_fqdn': get_fqdn('gitea', secrets, cluster_spec),
            'dex_url': get_fqdn('bouncer', secrets, cluster_spec),
        }
    }
    data['values'].update(secrets['gitea'])

    install_app(ctx, app_name, cluster_spec, data, app_name, install)


@task()
def gitea_port_forward(ctx):
    """
    Port forward gitea to localhost. Execute in a separate terminal, prior to apps.gitea-provision.
    """
    ctx.run("kubectl --context=admin@{} --namespace gitea port-forward statefulsets/gitea 3000:3000".format(
        get_constellation().bary.name
    ), echo=True)


@task(gitea)
def gitea_provision(ctx, ingress=False):
    """
    Provision local gitea, so that it works with Argo
    """
    cluster_spec = get_cluster_spec_from_context(ctx)
    secrets = get_secrets()

    gitea_fqdn = 'localhost:3000'
    if ingress:
        gitea_fqdn = get_fqdn('gitea', secrets, cluster_spec)

    data = {
        'cluster_domain': cluster_spec.name + '.local',
        'gitea_fqdn': gitea_fqdn,
        'dex_url': get_fqdn('bouncer', secrets, cluster_spec),
    }
    data.update(secrets['gitea'])

    gitea = Gitea(
        "https://" if ingress else "http://" + data['gitea_fqdn'],
        auth=(
            secrets['gitea']['admin_user'],
            secrets['gitea']['admin_password'])
    )

    admin = gitea.get_user()
    print("Gitea Version: " + gitea.get_version())
    print("API-Token belongs to user: " + admin.username)

    gitea.create_org(admin, 'gocy', "GOCY configuration")
    gocy = Organization.request(gitea, 'gocy')

    gocy.commit()
    constellation_name = get_ccontext()
    gocy.create_repo(
        constellation_name,
        'Configuration of {} constellation'.format(constellation_name),
        autoInit=False
    )


@task()
def dbs(ctx):
    app_name = 'dbs'
    app_directory = os.path.join('apps', app_name)
    cluster_spec = get_cluster_spec_from_context(ctx)
    secrets = get_secrets()

    data = {
        'values': {
            'cluster_domain': cluster_spec.name + '.local',
            'cluster_name': cluster_spec.name,
            'cockroach_fqdn': get_fqdn('cockroach', secrets, cluster_spec),
            'oauth_fqdn': get_fqdn('oauth', secrets, cluster_spec),
        }
    }
    data.update(secrets['dbs'])

    values_file = render_values(ctx, cluster_spec, app_name, data)

    namespace_file = os.path.join(app_directory, 'namespace.yaml')
    if os.path.isfile(namespace_file):
        ctx.run("kubectl apply -f " + namespace_file, echo=True)

    ctx.run("helm upgrade --dependency-update --install --namespace dbs "
            "--values={} "
            "dbs {} ".format(
                values_file,
                app_directory
            ), echo=True)


def _helm_install(ctx, values_file_path: str, app_name: str,
                  namespace=None, namespace_file_name='namespace.yaml', wait=False):
    app_directory = os.path.dirname(values_file_path)
    namespace_file_path = os.path.join(app_directory, namespace_file_name)

    if os.path.isfile(namespace_file_path):
        ctx.run("kubectl apply -f " + namespace_file_path, echo=True)
        with open(namespace_file_path) as namespace_file:
            namespace = dict(yaml.safe_load(namespace_file))['metadata']['name']

        namespace_cmd = "--namespace " + namespace
    else:
        if namespace is None:
            namespace = app_name

        namespace_cmd = "--create-namespace --namespace " + namespace

    ctx.run("helm upgrade --dependency-update "
            "{}"
            "--install {} "
            "{} {} ".format(
                "--wait " if wait else '',
                namespace_cmd,
                app_name,
                app_directory
            ), echo=True)


def helm_install(ctx, values_files: dict, app_name,
                 namespace=None, namespace_file_name='namespace.yaml', install: bool = False):
    if not install:
        return

    for dependency in values_files['deps']:
        _helm_install(ctx, dependency, app_name + '-dep', namespace, namespace_file_name, True)

    for app in values_files['apps']:
        _helm_install(ctx, app, app_name, namespace, namespace_file_name)


@task()
def dashboards(ctx, install: bool = False):
    app_name = 'dashboards'
    cluster_spec = get_cluster_spec_from_context(ctx)
    secrets = get_secrets()

    data = {
        'values': {
            'k8s_dashboard_fqdn': get_fqdn(['k8s', cluster_spec.name, 'dash'], secrets, cluster_spec),
            'rook_fqdn': get_fqdn(['rook', cluster_spec.name, 'dash'], secrets, cluster_spec),
            'hubble_fqdn': get_fqdn(['hubble', cluster_spec.name, 'dash'], secrets, cluster_spec),
            'oauth_fqdn': get_fqdn('oauth', secrets, cluster_spec),
        }
    }

    install_app(ctx, app_name, cluster_spec, data, app_name, install)


@task()
def harbor(ctx, install: bool = False):
    app_name = 'harbor'
    cluster_spec = get_cluster_spec_from_context(ctx)
    secrets = get_secrets()

    data = {
        'values': {
            'harbor_fqdn': get_fqdn('harbor', secrets, cluster_spec)
        }
    }
    data['values'].update(secrets['harbor'])

    install_app(ctx, app_name, cluster_spec, data, app_name, install)


@task()
def observability(ctx, install: bool = False):
    app_name = 'observability'
    cluster_spec = get_cluster_spec_from_context(ctx)
    secrets = get_secrets()

    data = {
        'values': {
            'jaeger_fqdn': get_fqdn('jaeger', secrets, cluster_spec),
            'oauth_fqdn': get_fqdn('oauth', secrets, cluster_spec),
            'grafana_fqdn': get_fqdn('grafana', secrets, cluster_spec),
            'cluster_name': cluster_spec.name + '.local'
        }
    }
    data['values'].update(secrets['grafana'])

    install_app(ctx, app_name, cluster_spec, data, app_name, install)


@task()
def ingress(ctx, install: bool = False):
    """
    Install Helm chart apps/ingress-bundle
    """
    app_name = 'ingress'
    cluster_spec = get_cluster_spec_from_context(ctx)

    with open(get_ip_addresses_file_path(cluster_spec, VipRole.ingress)) as ip_addresses_file:
        ingress_vips = ReservedVIPs().parse_raw(ip_addresses_file.read())

    data = {
        'values': {
            'address_pool_name': 'ingress-public-ipv4',
            'ingress_class_name': 'nginx',
            'ingress_class_default': True
        }
    }

    install_app(ctx, app_name, cluster_spec, data, app_name, install)

    if len(ingress_vips.global_ipv4) > 0:
        data = {
            'values': {
                'address_pool_name': 'ingress-global-ipv4',
                'ingress_class_name': 'nginx-global',
                'ingress_class_default': False
            }
        }
        values_file = render_values(ctx, cluster_spec, app_name + '-global', data,
                                    app_dir_name=app_name,
                                    target_app_suffix="global", namespace=app_name)
        helm_install(ctx, values_file, app_name + '-global', namespace=app_name, install=install)


@task()
def storage(ctx, install: bool = False):
    """
    Install storage
    """
    app_name = 'storage'
    cluster_spec = get_cluster_spec_from_context(ctx)
    data = {
        'values': {
            'operator_namespace': app_name
        },
        'deps': {
            'rook': {}
        }
    }

    install_app(ctx, app_name, cluster_spec, data, app_name, install)


def idp_auth_chart(ctx, app_name, cluster: Cluster, data: dict, install: bool):
    install_app(ctx, app_name, cluster, data, app_name, install)


def idp_auth_kubelogin_chart(ctx, cluster: Cluster, namespace: str, data: dict, install: bool):
    app_name = 'idp-auth-kubelogin'
    install_app(ctx, app_name, cluster, data=data, namespace=namespace, install=install)


@task()
def idp_auth(ctx, install: bool = False):
    """
    Produces ${HOME}/.gocy/[constellation_name]/[cluster_name]/idp-auth-values.yaml
    Uses it to install idp-auth. IDP should be installed on bary cluster only.
    """
    secrets = get_secrets()
    jinja = get_jinja()
    cluster = get_cluster_spec_from_context(ctx)
    constellation = get_constellation()
    data = {
        'values': {
            'bouncer_fqdn': get_fqdn('bouncer', secrets, cluster),
            'oauth_fqdn': get_fqdn('oauth', secrets, cluster),
            'argo_fqdn': get_fqdn('argo', secrets, cluster),
            'gitea_fqdn': get_fqdn('gitea', secrets, cluster)
        }
    }
    data['values'].update(secrets)

    app_name = 'idp-auth'
    if cluster.name == constellation.bary.name:
        idp_auth_chart(ctx, app_name, cluster, data, install)

    idp_auth_kubelogin_chart(ctx, cluster, app_name, data, install)

    with open(os.path.join(
            'templates',
            'patch',
            'oidc',
            'control-plane.jinja.yaml')) as talos_oidc_patch_file:
        talos_oidc_patch_tpl = jinja.from_string(talos_oidc_patch_file.read())

    talos_oidc_patch = talos_oidc_patch_tpl.render(data['values'])
    talos_oidc_patch_dir = os.path.join(get_secrets_dir(), 'patch', 'oidc')

    ctx.run("mkdir -p " + talos_oidc_patch_dir, echo=True)
    talos_oidc_patch_file_path = os.path.join(talos_oidc_patch_dir, 'talos_oidc_patch.yaml')
    with open(talos_oidc_patch_file_path, 'w') as talos_oidc_patch_file:
        talos_oidc_patch_file.write(talos_oidc_patch)

    cluster_nodes = get_nodes_ips(ctx)
    ctx.run("talosctl --nodes {} patch mc -p @{}".format(
        ",".join(cluster_nodes.control_plane),
        talos_oidc_patch_file_path
    ), echo=True)
