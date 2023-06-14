import os
from glob import glob
from pathlib import Path
from shutil import copytree, ignore_patterns

import yaml
from gitea import *
from invoke import task
from tabulate import tabulate

from tasks.ReservedVIPs import ReservedVIPs
from tasks.constellation_v01 import Cluster, VipRole
from tasks.helpers import get_secrets_dir, get_cluster_spec_from_context, get_secret_envs, get_nodes_ips, get_secrets, \
    get_constellation, get_jinja, get_fqdn, get_cluster_secrets_dir, get_ccontext, get_ip_addresses_file_path


def render_values_file(ctx, source: str, target: str, data: dict):
    jinja = get_jinja()
    ctx.run('mkdir -p ' + str(Path(target).parent.absolute()))
    with open(source) as source_file:
        template = jinja.from_string(source_file.read())

    with open(target, 'w') as target_file:
        rendered_list = [line for line in template.render(data).splitlines() if len(line.rstrip()) > 0]
        target_file.write(os.linesep.join(rendered_list))


def render_values(ctx, cluster: Cluster, app_folder_name, data,
                  apps_dir_name='apps',
                  template_file_name='values.jinja.yaml',
                  target_file_name='values.yaml') -> str:
    """
    Renders jinja style helm values templates to ~/.gocy/[constellation]/[cluster]/apps to be picked up by Argo.
    """
    source_apps_path = os.path.join(apps_dir_name, app_folder_name)
    target_apps_path = os.path.join(get_cluster_secrets_dir(cluster), source_apps_path)
    copytree(source_apps_path, target_apps_path, ignore=ignore_patterns(template_file_name), dirs_exist_ok=True)

    target = os.path.join(target_apps_path, target_file_name)
    render_values_file(ctx,
                       os.path.join(source_apps_path, template_file_name),
                       target,
                       data)

    return target


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
def create_dns_tls_namespace(ctx):
    """
    Create namespace to be shared by external-dns and cert-manager
    """
    ctx.run('kubectl create namespace {} | true'.format(get_dns_tls_namespace_name()), echo=True)


@task()
def gcloud_login(ctx):
    """
    If you rae using gcp and your DNS provider, you can use this to log in to the console.
    """
    ctx.run("gcloud auth login", echo=True)


@task(create_dns_tls_namespace)
def deploy_dns_management_token(ctx, provider='google'):
    """
    Creates the DNS token secret to be used by external-dns and cert-manager
    """
    if provider == 'google':
        get_google_dns_token(ctx)

        ctx.run("kubectl -n {} create secret generic '{}' --from-file=credentials.json={} | true".format(
            get_dns_tls_namespace_name(),
            os.environ.get('GCP_SA_NAME'),
            get_gcp_token_file_name()
        ), echo=True)

    else:
        print("Unsupported DNS provider: " + provider)


@task(deploy_dns_management_token)
def dns_and_tls_dependencies(ctx):
    """
    Install Helm chart apps/dns-and-tls-dependencies
    """
    dns_tls_directory = os.path.join('apps', 'dns-and-tls-dependencies')
    secrets = get_secret_envs()
    with ctx.cd(dns_tls_directory):
        ctx.run("helm dependency build", echo=True)
        ctx.run("helm upgrade --wait --install --namespace {} "
                "--set external_dns.provider.google.google_project={} "
                "--set external_dns.provider.google.domain_filter={} "
                "dns-and-tls-dependencies ./".format(
                    get_dns_tls_namespace_name(),
                    secrets['GCP_PROJECT_ID'],
                    secrets['GOCY_DOMAIN']
                ), echo=True)


@task(dns_and_tls_dependencies)
def dns_and_tls(ctx):
    """
    Install Helm chart apps/dns-and-tls, apps/dns-and-tls-dependencies
    """
    dns_tls_directory = os.path.join('apps', 'dns-and-tls')
    secrets = get_secret_envs()
    with ctx.cd(dns_tls_directory):
        ctx.run("helm upgrade --install --namespace {} "
                "--set letsencrypt.email={} "
                "--set letsencrypt.google.project_id={} "
                "dns-and-tls ./".format(
                    get_dns_tls_namespace_name(),
                    secrets['GOCY_ADMIN_EMAIL'],
                    secrets['GCP_PROJECT_ID']
                ), echo=True)


@task()
def whoami(ctx, oauth: bool = False):
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
        'whoami_fqdn': fqdn,
        'name': cluster_spec.name,
        'oauth_enabled': oauth,
        'oauth_fqdn': 'https://' + get_fqdn('oauth', secrets, cluster_spec)
    }

    values_file = render_values(ctx, cluster_spec, 'whoami', data)
    helm_install(ctx, values_file, app_name, 'test-application')


@task
def argo(ctx):
    app_directory = os.path.join('apps', 'argocd')
    cluster_spec = get_cluster_spec_from_context(ctx)
    secrets = get_secrets()

    data = {
        'argocd_fqdn': get_fqdn('argo', secrets, cluster_spec),
        'bouncer_fqdn': get_fqdn('bouncer', secrets, cluster_spec),
        'client_secret': secrets['env']['GOCY_ARGOCD_SSO_CLIENT_SECRET'],
        'constellation': get_ccontext()
    }

    values_file = render_values(ctx, cluster_spec, 'argocd', data)
    ctx.run("helm upgrade --install --namespace argocd --create-namespace "
            "--values={} "
            "argocd {} ".format(
                values_file,
                app_directory
            ), echo=True)


@task
def gitea(ctx):
    """
    Install gitea
    """
    app_name = 'gitea'
    cluster_spec = get_cluster_spec_from_context(ctx)
    secrets = get_secrets()

    data = {
        'cluster_domain': cluster_spec.name + '.local',
        'gitea_fqdn': get_fqdn('gitea', secrets, cluster_spec),
        'dex_url': get_fqdn('bouncer', secrets, cluster_spec),
    }
    data.update(secrets['gitea'])

    values_file = render_values(ctx, cluster_spec, app_name, data)
    helm_install(ctx, values_file, app_name)


@task()
def gitea_port_forward(ctx):
    """
    Port forward gitea to localhost. Execute in a separate terminal, prior to apps.gitea-provision.
    """
    ctx.run("kubectl -n gitea port-forward statefulsets/gitea 3000:3000", echo=True)


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


@task
def dbs(ctx):
    app_name = 'dbs'
    app_directory = os.path.join('apps', app_name)
    cluster_spec = get_cluster_spec_from_context(ctx)
    secrets = get_secrets()

    data = {
        'cluster_domain': cluster_spec.name + '.local',
        'cluster_name': cluster_spec.name,
        'cockroach_fqdn': get_fqdn('cockroach', secrets, cluster_spec),
        'oauth_fqdn': get_fqdn('oauth', secrets, cluster_spec),
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


def helm_install(ctx, values_file, app_name, namespace=None, namespace_file_name='namespace.yaml'):
    app_directory = os.path.join('apps', app_name)
    namespace_file_path = os.path.join(app_directory, namespace_file_name)
    namespace_cmd = ''
    if namespace is not None:
        namespace_cmd = "--create-namespace --namespace " + namespace

    if os.path.isfile(namespace_file_path):
        ctx.run("kubectl apply -f " + namespace_file_path, echo=True)
        with open(namespace_file_path) as namespace_file:
            namespace = dict(yaml.safe_load(namespace_file))['metadata']['name']

        namespace_cmd = "--namespace " + namespace

    ctx.run("helm upgrade --dependency-update --install {} "
            "--values={} "
            "{} {} ".format(
                namespace_cmd,
                values_file,
                namespace if namespace is not None else app_name,
                app_directory
            ), echo=True)


@task
def dashboards(ctx):
    app_name = 'dashboards'
    cluster_spec = get_cluster_spec_from_context(ctx)
    secrets = get_secrets()

    data = {
        'k8s_dashboard_fqdn': get_fqdn(['k8s', 'dash'], secrets, cluster_spec),
        'rook_fqdn': get_fqdn(['rook', 'dash'], secrets, cluster_spec),
        'hubble_fqdn': get_fqdn(['hubble', 'dash'], secrets, cluster_spec),
        'oauth_fqdn': get_fqdn('oauth', secrets, cluster_spec),
    }

    values_file = render_values(ctx, cluster_spec, app_name, data)
    helm_install(ctx, values_file, app_name)


@task
def harbor(ctx):
    app_name = 'harbor'
    cluster_spec = get_cluster_spec_from_context(ctx)
    secrets = get_secrets()

    data = {
        'harbor_fqdn': get_fqdn('harbor', secrets, cluster_spec)
    }
    data.update(secrets['harbor'])

    values_file = render_values(ctx, cluster_spec, app_name, data)
    helm_install(ctx, values_file, app_name)


@task
def observability(ctx):
    app_name = 'observability'
    cluster_spec = get_cluster_spec_from_context(ctx)
    secrets = get_secrets()

    data = {
        'jaeger_fqdn': get_fqdn('jaeger', secrets, cluster_spec),
        'oauth_fqdn': get_fqdn('oauth', secrets, cluster_spec),
        'grafana_fqdn': get_fqdn('grafana', secrets, cluster_spec),
        'cluster_name': cluster_spec.name + '.local'
    }
    data.update(secrets['grafana'])

    values_file = render_values(ctx, cluster_spec, app_name, data)
    helm_install(ctx, values_file, app_name)


@task()
def ingress_controller(ctx):
    """
    Install Helm chart apps/ingress-bundle
    """
    app_name = 'ingress-bundle'
    cluster_spec = get_cluster_spec_from_context(ctx)

    with open(get_ip_addresses_file_path(cluster_spec, VipRole.ingress)) as ip_addresses_file:
        ingress_vips = ReservedVIPs().parse_raw(ip_addresses_file.read())

    address_pool_name = 'ingress-public-ipv4'
    ingress_class_name = 'nginx'
    ingress_class_default = True
    target_file_name = 'values.yaml'

    if len(ingress_vips.global_ipv4) > 0:
        address_pool_name = 'ingress-global-ipv4'
        ingress_class_name = 'nginx-global'
        ingress_class_default = False
        target_file_name = 'values.global.yaml'

    data = {
        'address_pool_name': address_pool_name,
        'ingress_class_name': ingress_class_name,
        'ingress_class_default': ingress_class_default
    }

    values_file = render_values(ctx, cluster_spec, app_name, data, target_file_name=target_file_name)
    helm_install(ctx, values_file, app_name, namespace=app_name)


@task()
def persistent_storage(ctx):
    """
    Install persistent-storage
    """
    app_directory = os.path.join('apps', 'persistent-storage-dependencies')
    with ctx.cd(app_directory):
        ctx.run("kubectl apply -f namespace.yaml", echo=True)
        ctx.run("helm upgrade "
                "--dependency-update "
                "--install "
                "--namespace persistent-storage "
                "persistent-storage ./", echo=True)

    app_directory = os.path.join('apps', 'persistent-storage')
    with ctx.cd(app_directory):
        ctx.run("helm upgrade "
                "--install "
                "--namespace persistent-storage "
                "--set rook-ceph-cluster.operatorNamespace=persistent-storage "
                "persistent-storage-cluster ./",
                echo=True)


def idp_auth_chart(ctx, cluster: Cluster, secrets):
    app_directory = os.path.join('apps', 'idp-auth')
    values_file = render_values(ctx, cluster, 'idp-auth', secrets)

    ctx.run("kubectl apply -f {}".format(
        os.path.join(app_directory, 'namespace.yaml')
    ), echo=True)
    ctx.run("helm upgrade "
            "--dependency-update "
            "--install "
            "--namespace idp-auth "
            "--values {} "
            "idp-auth {}".format(
        values_file,
        app_directory), echo=True)


def idp_auth_kubelogin_chart(ctx, cluster: Cluster, values_template_file, jinja, secrets):
    app_directory = os.path.join('apps', 'idp-auth-kubelogin')

    if values_template_file is None:
        values_template_file = os.path.join(app_directory, 'values.jinja.yaml')

    with open(values_template_file) as values_file:
        values_yaml = values_file.read()

    cluster_yaml_tpl = jinja.from_string(values_yaml)
    values_yaml = cluster_yaml_tpl.render(secrets)

    idp_auth_values_yaml = os.path.join(get_secrets_dir(), cluster.name, 'idp-auth-kubelogin-values.yaml')
    with open(idp_auth_values_yaml, 'w') as idp_auth_values_yaml_file:
        idp_auth_values_yaml_file.write(values_yaml)

    ctx.run("helm upgrade "
            "--dependency-update "
            "--install "
            "--namespace idp-auth "
            "--create-namespace "
            "--values {} "
            "idp-auth-kubelogin {}".format(
        idp_auth_values_yaml,
        app_directory), echo=True)


@task()
def idp_auth(ctx, values_template_file=None):
    """
    Produces ${HOME}/.gocy/[constellation_name]/[cluster_name]/idp-auth-values.yaml
    Uses it to install idp-auth. IDP should be installed on bary cluster only.
    """

    data = get_secrets()
    jinja = get_jinja()
    cluster = get_cluster_spec_from_context(ctx)
    constellation = get_constellation()
    data['bouncer_fqdn'] = get_fqdn('bouncer', data, cluster)
    data['oauth_fqdn'] = get_fqdn('oauth', data, cluster)
    data['argo_fqdn'] = get_fqdn('argo', data, cluster)
    data['gitea_fqdn'] = get_fqdn('gitea', data, cluster)

    if cluster.name == constellation.bary.name:
        idp_auth_chart(ctx, cluster, data)

    idp_auth_kubelogin_chart(ctx, cluster, values_template_file, jinja, data)

    with open(os.path.join(
            'templates',
            'patch',
            'oidc',
            'control-plane.jinja.yaml')) as talos_oidc_patch_file:
        talos_oidc_patch_tpl = jinja.from_string(talos_oidc_patch_file.read())

    talos_oidc_patch = talos_oidc_patch_tpl.render(data)
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
