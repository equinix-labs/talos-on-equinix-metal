import os

from invoke import task
from tasks_pkg.helpers import get_secrets_dir, get_cluster_spec_from_context


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

    ctx.run("gcloud iam service-accounts keys create {} --iam-account {}@{}.iam.gserviceaccount.com".format(
        get_gcp_token_file_name(),
        os.environ.get('GCP_SA_NAME'),
        os.environ.get('GCP_PROJECT_ID')
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

    ctx.run("kubectl -n {} create secret generic '{}' --from-file=credentials.json={}".format(
        get_dns_tls_namespace_name(),
        os.environ.get('GCP_SA_NAME'),
        get_gcp_token_file_name()
    ), echo=True)


@task()
def install_dns_and_tls_dependencies(ctx):
    dns_tls_directory = os.path.join('apps', 'dns-and-tls-dependencies')
    with ctx.cd(dns_tls_directory):
        ctx.run("helm dependency build", echo=True)
        ctx.run("helm upgrade --wait --install --namespace {} "
                "--set external_dns.provider.google.google_project={} "
                "--set external_dns.provider.google.domain_filter={} "
                "dns-and-tls-dependencies ./".format(
                    get_dns_tls_namespace_name(),
                    os.environ.get('GCP_PROJECT_ID'),
                    os.environ.get('GCP_DOMAIN')
                ), echo=True)


@task(install_dns_and_tls_dependencies)
def install_dns_and_tls(ctx):
    dns_tls_directory = os.path.join('apps', 'dns-and-tls')
    with ctx.cd(dns_tls_directory):
        ctx.run("helm upgrade --install --namespace {} "
                "--set letsencrypt.email={} "
                "--set letsencrypt.google.project_id={} "
                "dns-and-tls ./".format(
                    get_dns_tls_namespace_name(),
                    os.environ.get('TOEM_ADMIN_EMAIL'),
                    os.environ.get('GCP_PROJECT_ID')
                ), echo=True)


@task()
def install_whoami_app(ctx):
    dns_tls_directory = os.path.join('apps', 'whoami')
    cluster_spec = get_cluster_spec_from_context(ctx)
    with ctx.cd(dns_tls_directory):
        ctx.run("kubectl apply -f namespace.yaml", echo=True)
        ctx.run("helm upgrade --install --namespace test-application "
                "--set test_app.fqdn={} "
                "--set test_app.name={} "                
                "whoami-test-app ./".format(
                    "whoami.{}.{}".format(
                        os.environ.get('TOEM_TEST_SUBDOMAIN'),
                        os.environ.get('GCP_DOMAIN')
                    ), cluster_spec['name']
                ), echo=True)


@task()
def install_ingress_controller(ctx):
    app_directory = os.path.join('apps', 'ingress-bundle')
    with ctx.cd(app_directory):
        ctx.run("helm dependency update", echo=True)
        ctx.run("helm upgrade --install ingress-bundle --namespace ingress-bundle --create-namespace ./", echo=True)
