from pprint import pprint

import pexpect
from packaging import version


class Metal:
    _cmd: str = "metal"

    def version(self):
        version_raw = pexpect.spawn(" ".join([self._cmd, '--version']))

        for line in range(0, 5):
            result = version_raw.expect([r"\n.*?([0-9\.]+)", pexpect.EOF])
            print(result)
            if result == 0:
                pprint(version_raw.match.groups())

        # version_str = version_raw.match.groups()[0]
        # version_obj = version.parse(version_str)
        #
        # print(version_obj)
