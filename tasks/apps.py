import os
from pathlib import Path

from invoke import task

from tasks.constellation_v01 import Cluster
from tasks.helpers import get_secrets_dir, get_cluster_spec_from_context, get_secret_envs, get_nodes_ips, get_secrets, \
    get_constellation, get_jinja, get_fqdn, get_cluster_secrets_dir


def render(ctx, source: str, target: str, data: dict):
    jinja = get_jinja()
    ctx.run('mkdir -p ' + str(Path(target).parent.absolute()))
    with open(source) as source_file:
        template = jinja.from_string(source_file.read())

    with open(target, 'w') as target_file:
        target_file.write(template.render(data))


def render_values(ctx, cluster: Cluster, app_folder_name, data) -> str:
    """
    Renders jinja style helm values templates to ~/.gocy/[constellation]/[cluster]/apps to be picked up by Argo.
    """
    apps_dir = 'apps'
    app_dir = os.path.join(apps_dir, app_folder_name)
    target_app_dir = os.path.join(get_cluster_secrets_dir(cluster), app_dir)
    target = os.path.join(target_app_dir, 'values.yaml')
    render(ctx,
           os.path.join(app_dir, 'values.tpl.yaml'),
           target,
           data)

    return target


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
def install_dns_and_tls_dependencies(ctx):
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


@task(install_dns_and_tls_dependencies)
def install_dns_and_tls(ctx):
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
def install_whoami_app(ctx, oauth: bool = False):
    """
    Install Helm chart apps/whoami
    """
    app_directory = os.path.join('apps', 'whoami')
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

    ctx.run("kubectl apply -f {}".format(os.path.join(app_directory, 'namespace.yaml')), echo=True)
    ctx.run("helm upgrade --install --namespace test-application "
            "--values={} "
            "whoami-test-app {}".format(
                values_file,
                app_directory), echo=True)


@task
def install_argo(ctx):
    app_directory = os.path.join('apps', 'argocd')
    cluster_spec = get_cluster_spec_from_context(ctx)
    secrets = get_secrets()

    data = {
        'argocd_fqdn': get_fqdn('argo', secrets, cluster_spec),
        'bouncer_fqdn': get_fqdn('bouncer', secrets, cluster_spec),
        'client_secret': secrets['env']['GOCY_ARGOCD_SSO_CLIENT_SECRET']
    }

    values_file = render_values(ctx, cluster_spec, 'argocd', data)
    ctx.run("helm upgrade --install --namespace argocd --create-namespace "
            "--values={} "
            "argocd {} ".format(
                values_file,
                app_directory
            ), echo=True)


@task()
def install_ingress_controller(ctx):
    """
    Install Helm chart apps/ingress-bundle
    """
    app_directory = os.path.join('apps', 'ingress-bundle')
    with ctx.cd(app_directory):
        ctx.run("helm dependency update", echo=True)
        ctx.run("helm upgrade --install ingress-bundle --namespace ingress-bundle --create-namespace ./", echo=True)


@task()
def install_persistent_storage(ctx):
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


def install_idp_auth_chart(ctx, cluster: Cluster, secrets):
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


def install_idp_auth_kubelogin_chart(ctx, cluster: Cluster, values_template_file, jinja, secrets):
    app_directory = os.path.join('apps', 'idp-auth-kubelogin')

    if values_template_file is None:
        values_template_file = os.path.join(app_directory, 'values.tpl.yaml')

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
def install_idp_auth(ctx, values_template_file=None):
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

    if cluster.name == constellation.bary.name:
        install_idp_auth_chart(ctx, cluster, data)

    install_idp_auth_kubelogin_chart(ctx, cluster, values_template_file, jinja, data)

    with open(os.path.join(
            'patch-templates',
            'oidc',
            'control-plane.pt.yaml')) as talos_oidc_patch_file:
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

