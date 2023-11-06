import os
import platform

import requests
from packaging import version
from packaging.version import Version

from tasks.dao.ProjectPaths import ProjectPaths
from tasks.wrappers import Logger


class GitHub:

    _machine: str
    _os: str
    _logger: Logger

    def __init__(self):
        self._logger = Logger.get()
        self._os = platform.system().lower()
        self._machine = platform.machine()
        self._logger.info("Running on {} | {}".format(self._machine, self._os))

    def get_latest_version_url(self, url: str) -> (Version, list[str]):
        response = requests.get(url)  # https://api.github.com/repos/helm/helm/releases/latest
        if response.status_code == 200:
            data = response.json()
            assets = data.get('assets', [])
            tag_name = version.parse(data.get('tag_name', None))
            dl_urls = list()

            for asset in assets:
                download_url = asset['browser_download_url']
                if self._machine in download_url and self._os in download_url:
                    dl_urls.append(download_url)

            if len(dl_urls) < 1:
                self._logger.fatal("Failed to find compatible binary")

            return tag_name, dl_urls
        else:
            self._logger.fatal("GitHub: No meaningful response")

    def download(self, url: str, target: str):
        paths = ProjectPaths()
        target = paths.get_bin(target)
        response = requests.get(url, stream=True)
        if response.status_code == 200:
            with open(target, 'wb') as file:
                for chunk in response.iter_content(chunk_size=8192):
                    file.write(chunk)
            self._logger.debug('{} downloaded successfully.'.format(target))
            os.chmod(target, 0o755)
        else:
            self._logger.fatal('Failed to download {}'.format(target))