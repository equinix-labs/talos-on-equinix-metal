import os
import re

import pexpect
from pexpect import spawn

from tasks.dao.ProjectPaths import ProjectPaths
from tasks.wrappers import Logger


KNOWN_COMMANDS = [
    'kubectl',
    'metal',
    'helm',
    'cilium',
    'talosctl'
]


class Expect:
    _base_command: str

    def __init__(self, base_command: str = None):
        if base_command is not None and base_command in KNOWN_COMMANDS:
            self._base_command = base_command

            paths = ProjectPaths()
            local_path = paths.get_bin(base_command)

            if os.path.exists(local_path):
                self._base_command = local_path
        else:
            print("Unknown command: {}".format(base_command))

    def run(self, params: list[str], pattern: str = None) -> [str, spawn]:
        base_command = [self._base_command]
        base_command.extend(params)

        cmd = " ".join(base_command)
        Logger.get('Expect').debug("Running command: {}".format(cmd))

        process = pexpect.spawn(cmd)
        process.expect(pexpect.EOF)
        output = process.before.decode().strip()
        if pattern is not None:
            matches = re.findall(pattern, output)
            output = matches[0]

        return output, process

# def _capture_df_output():
#     # Spawn a new process running the command
#     process = pexpect.spawn('df -h')
#
#     # Wait for the command to finish and capture the output
#     process.expect(pexpect.EOF)
#     output = process.before.decode().strip()
#
#     # Split the output into lines
#     lines = output.splitlines()
#
#     # Extract the headers and remove leading/trailing spaces
#     headers = [header.strip() for header in re.split(r'\s+', lines[0])]
#
#     # Initialize an empty result list
#     result = []
#
#     # Parse the data, skipping the headers
#     for line in lines[1:]:
#         # Split the line into fields and remove leading/trailing spaces
#         fields = [field.strip() for field in re.split(r'\s+', line)]
#
#         # Create a dictionary using the headers as keys
#         entry = {header: field for header, field in zip(headers, fields)}
#
#         # Add the entry to the result list
#         result.append(entry)
#
#     return result
