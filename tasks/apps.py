import configparser
import os

import yaml
from invoke import task
from tasks.helpers import get_secrets_dir, get_cluster_spec_from_context, get_secrets


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

    secrets = get_secrets()
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
    secrets = get_secrets()
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
    secrets = get_secrets()
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
    secrets = get_secrets()
    
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
def install_idp_auth(ctx):
    """
    Produces ${HOME}/.gocy/[constellation_name]/[cluster_name]/idp-auth-values.yaml
    Uses it to install idp-auth. IDP should be installed on bary cluster only.
    """
    app_directory = os.path.join('apps', 'idp-auth')
    secrets = get_secrets()
    cluster = get_cluster_spec_from_context(ctx)

    with open(os.path.join(app_directory, 'values.yaml')) as values_file:
        values = dict(yaml.safe_load(values_file))

    domain = secrets['GOCY_DOMAIN']
    bouncer_fqdn = "bouncer.{}".format(domain)
    values['dex']['config']['issuer'] = "https://{}".format(bouncer_fqdn)
    values['dex']['config']['staticClients'][0]['secret'] = secrets['GOCY_OAUTH_CLIENT_SECRET']
    values['dex']['config']['staticClients'][0]['redirectURIs'][0] = "https://oauth.{}/oauth2/callback".format(domain)
    values['dex']['config']['staticClients'][1]['secret'] = secrets['GOCY_ARGOCD_SSO_CLIENT_SECRET']
    values['dex']['config']['staticClients'][1]['redirectURIs'][0] = "https://argocd.{}/auth/callback".format(domain)
    values['dex']['config']['staticClients'][2]['secret'] = secrets['GOCY_PINNIPED_SSO_CLIENT_SECRET']
    values['dex']['config']['staticClients'][2]['redirectURIs'][0] = "https://pinniped.{}/callback".format(domain)

    values['dex']['config']['staticPasswords'][0]['email'] = "eric@{}".format(domain)
    eric_password_hash = ctx.run('echo "{}" | htpasswd -BinC 10 eirc | cut -d: -f2'.format(
        secrets['ERIC_PASS']), hide='stdout', echo=False).stdout.strip()
    values['dex']['config']['staticPasswords'][0]['hash'] = eric_password_hash

    values['dex']['config']['staticPasswords'][1]['email'] = "kenny@{}".format(domain)
    kenny_password_hash = ctx.run('echo "{}" | htpasswd -BinC 10 kenny | cut -d: -f2'.format(
        secrets['KENNY_PASS']), hide='stdout', echo=False).stdout.strip()
    values['dex']['config']['staticPasswords'][1]['hash'] = kenny_password_hash

    values['dex']['config']['connectors'][0]['config']['clientID'] = secrets['GOCY_GH_CLIENT_ID']
    values['dex']['config']['connectors'][0]['config']['clientSecret'] = secrets['GOCY_GH_CLIENT_SECRET']
    values['dex']['config']['connectors'][0]['config']['redirectURI'] = "https://{}/callback".format(bouncer_fqdn)
    values['dex']['config']['connectors'][0]['config']['orgs'][0]['name'] = secrets['GCP_PROJECT_ID']

    values['dex']['ingress']['annotations']['external-dns.alpha.kubernetes.io/hostname'] = bouncer_fqdn
    values['dex']['ingress']['hosts'][0]['host'] = bouncer_fqdn
    values['dex']['ingress']['tls'][0]['secretName'] = "tls." + bouncer_fqdn
    values['dex']['ingress']['tls'][0]['hosts'][0] = bouncer_fqdn

    values['oauth2-proxy']['config']['clientSecret'] = secrets['GOCY_OAUTH_CLIENT_SECRET']
    values['oauth2-proxy']['config']['cookieSecret'] = secrets['GOCY_OAUTH_COOKIE_SECRET']

    oauth_cfg = configparser.ConfigParser()
    tainted_config = "[gocy]\n{}".format(values['oauth2-proxy']['config']['configFile'])
    oauth_cfg.read_string(tainted_config)

    oauth_cfg['gocy']['oidc_issuer_url'] = '"https://{}"'.format(bouncer_fqdn)
    oauth_cfg['gocy']['redirect_url'] = '"https://oauth.{}/oauth2/callback"'.format(domain)
    oauth_cfg['gocy']['whitelist_domains'] = '[ ".{}" ]'.format(domain)
    oauth_cfg['gocy']['cookie_domains'] = '[ ".{}" ]'.format(domain)

    tainted_oauth_cfg_ini = os.path.join(
            get_secrets_dir(),
            'tainted_oauth_cfg.ini')
    with open(tainted_oauth_cfg_ini, 'w') as tainted_oauth_cfg_file:
        oauth_cfg.write(tainted_oauth_cfg_file)

    with open(tainted_oauth_cfg_ini) as tainted_oauth_cfg_file:
        values['oauth2-proxy']['config']['configFile'] = "\n".join(
            tainted_oauth_cfg_file.read().splitlines()[1:]
        )

    oauth_fqdn = "oauth." + domain
    values['oauth2-proxy']['ingress']['annotations']['external-dns.alpha.kubernetes.io/hostname'] = oauth_fqdn
    values['oauth2-proxy']['ingress']['hosts'][0] = oauth_fqdn
    values['oauth2-proxy']['ingress']['tls'][0]['secretName'] = "tls." + oauth_fqdn
    values['oauth2-proxy']['ingress']['tls'][0]['hosts'][0] = oauth_fqdn

    idp_auth_values_yaml = os.path.join(get_secrets_dir(), 'idp-auth-values.yaml')
    with open(idp_auth_values_yaml, 'w') as idp_auth_values_yaml_file:
        yaml.dump(values, idp_auth_values_yaml_file)

    with ctx.cd(app_directory):
        ctx.run("kubectl apply -f namespace.yaml", echo=True)
        ctx.run("helm upgrade "
                "--dependency-update "
                "--install "
                "--namespace idp-auth "
                "--values {} "
                "idp-auth ./".format(idp_auth_values_yaml), echo=True)
