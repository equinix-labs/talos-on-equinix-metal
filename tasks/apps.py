import configparser
import os
from pprint import pprint

import jinja2
import yaml
from invoke import task
from tasks.helpers import get_secrets_dir, get_cluster_spec_from_context, get_secret_envs, get_nodes_ips, get_secrets


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
    dns_tls_directory = os.path.join('apps', 'whoami')
    cluster_spec = get_cluster_spec_from_context(ctx)
    secrets = get_secret_envs()
    
    if oauth:
        fqdn = "whoami-oauth.{}".format(
            secrets['GOCY_DOMAIN']
        )
    else:
        fqdn = "whoami.{}.{}".format(
            cluster_spec.domain_prefix,
            secrets['GOCY_DOMAIN']
        )

    with ctx.cd(dns_tls_directory):
        ctx.run("kubectl apply -f namespace.yaml", echo=True)
        if fqdn:
            ctx.run("helm upgrade --install --namespace test-application "
                    "--set test_app.fqdn={} "
                    "--set test_app.name={} "
                    "--set test_app.oauth.enabled=true "
                    "--set test_app.oauth.fqdn='{}' "
                    "whoami-test-app ./".format(
                        fqdn,
                        cluster_spec.name,
                        'https://oauth.{}'.format(secrets['GOCY_DOMAIN'])
                    ), echo=True)
        else:
            ctx.run("helm upgrade --install --namespace test-application "
                    "--set test_app.fqdn={} "
                    "--set test_app.name={} "
                    "whoami-test-app ./".format(
                        fqdn,
                        cluster_spec.name
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


@task()
def install_idp_auth(ctx, values_template_file=None, static_password_enabled=False):
    """
    Produces ${HOME}/.gocy/[constellation_name]/[cluster_name]/idp-auth-values.yaml
    Uses it to install idp-auth. IDP should be installed on bary cluster only.
    """
    app_directory = os.path.join('apps', 'idp-auth')
    secrets = get_secrets()

    if values_template_file is None:
        values_template_file = os.path.join(app_directory, 'values.tpl.yaml')

    with open(values_template_file) as values_file:
        values_yaml = values_file.read()

    jinja = jinja2.Environment(undefined=jinja2.StrictUndefined)
    cluster_yaml_tpl = jinja.from_string(values_yaml)
    values_yaml = cluster_yaml_tpl.render(secrets)

    idp_auth_values_yaml = os.path.join(get_secrets_dir(), 'idp-auth-values.yaml')
    with open(idp_auth_values_yaml, 'w') as idp_auth_values_yaml_file:
        idp_auth_values_yaml_file.write(values_yaml)

    ctx.run("kubectl apply -f {}".format(
        os.path.join(app_directory, 'namespace.yaml')
    ), echo=True)
    ctx.run("helm upgrade "
            "--dependency-update "
            "--install "
            "--namespace idp-auth "
            "--values {} "
            "idp-auth {}".format(
                idp_auth_values_yaml,
                app_directory), echo=True)

    with open(os.path.join(
            'patch-templates',
            'oidc',
            'control-plane.pt.yaml')) as talos_oidc_patch_file:
        talos_oidc_patch_tpl = jinja.from_string(talos_oidc_patch_file.read())

    talos_oidc_patch = talos_oidc_patch_tpl.render(secrets)
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
