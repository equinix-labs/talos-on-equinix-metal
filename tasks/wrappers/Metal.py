from packaging import version
from packaging.version import Version

from tasks.wrappers.Expect import Expect
from tasks.wrappers.GitHub import GitHub


class Metal:
    _expect: Expect
    _url: str

    def __init__(self):
        self._expect = Expect('metal')
        self._url = 'https://api.github.com/repos/equinix/metal-cli/releases/latest'

    def version(self) -> Version:
        _version, _ = self._expect.run(['--version'], r'\d+\.\d+\.\d+')
        return version.parse(_version)

    def run(self, params: list[str]):
        return self._expect.run(params)

    def dl_latest(self):
        github = GitHub()
        remote_version, urls = github.get_latest_version_url(self._url)
        if remote_version > self.version():
            github.download(urls[0], 'metal')

