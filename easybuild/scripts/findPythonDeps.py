#!/usr/bin/env python

import argparse
import json
import os
import pkg_resources
import re
import subprocess
import sys
import tempfile
from pprint import pprint


def extract_pkg_name(package_spec):
    return re.split('<|>|=|~', args.package, 1)[0]


def run_cmd(arguments, action_desc, **kwargs):
    """Run the command and return the return code and output"""
    extra_args = kwargs or {}
    if sys.version_info[0] >= 3:
        extra_args['universal_newlines'] = True
    p = subprocess.Popen(arguments, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, **extra_args)
    out, _ = p.communicate()
    if p.returncode != 0:
        raise RuntimeError('Failed to %s: %s' % (action_desc, out))
    return out


def run_in_venv(cmd, venv_path, action_desc):
    """Run the givven command in the virtualenv at the given path"""
    cmd = 'source %s/bin/activate && %s' % (venv_path, cmd)
    return run_cmd(cmd, action_desc, shell=True, executable='/bin/bash')


def get_dep_tree(package_spec):
    """Get the dep-tree for installing the given Python package spec"""
    package_name = extract_pkg_name(package_spec)
    with tempfile.TemporaryDirectory(suffix=package_name + '-deps') as tmp_dir:
        # prevent pip from (ab)using $HOME/.cache/pip
        os.environ['XDG_CACHE_HOME'] = os.path.join(tmp_dir, 'pip-cache')
        venv_dir = os.path.join(tmp_dir, 'venv')
        # create virtualenv, install package in it
        run_cmd(['virtualenv', '--system-site-packages', venv_dir], action_desc='create virtualenv')
        run_in_venv('pip install "%s"' % package_spec, venv_dir, action_desc='install ' + package_spec)
        # install pipdeptree, figure out dependency tree for installed package
        run_in_venv('pip install pipdeptree', venv_dir, action_desc='install pipdeptree')
        dep_tree = run_in_venv('pipdeptree -j -p "%s"' % package_name,
                               venv_dir, action_desc='collect dependencies')
    return json.loads(dep_tree)


def find_deps(pkgs, dep_tree):
    """Recursively resolve dependencies of the given package(s) and return them"""
    res = []
    for pkg in pkgs:
        matching_entries = [entry for entry in dep_tree
                            if pkg in (entry['package']['package_name'], entry['package']['key'])]
        if not matching_entries:
            raise RuntimeError("Found no installed package for '%s'" % pkg)
        if len(matching_entries) > 1:
            raise RuntimeError("Found multiple installed packages for '%s'" % pkg)
        entry = matching_entries[0]
        res.append((entry['package']['package_name'], entry['package']['installed_version']))
        deps = (dep['package_name'] for dep in entry['dependencies'])
        res.extend(find_deps(deps, dep_tree))
    return res


parser = argparse.ArgumentParser(
    description='Find dependencies of Python packages by installing it in a temporary virtualenv. ',
    epilog=' && '.join(['Example usage with EasyBuild: '
                        'eb TensorFlow-2.3.4.eb --dump-env',
                        'source TensorFlow-2.3.4.env',
                        sys.argv[0] + ' tensorflow==2.3.4'])
)
parser.add_argument('package', metavar='python-pkg-spec',
                    help='Python package spec, e.g. tensorflow==2.3.4')
parser.add_argument('--verbose', help='Verbose output', action='store_true')
args = parser.parse_args()

if args.verbose:
    print('Getting dep tree of ' + args.package)
dep_tree = get_dep_tree(args.package)
if args.verbose:
    print('Extracting dependencies of ' + args.package)
deps = find_deps([extract_pkg_name(args.package)], dep_tree)

installed_modules = {mod.project_name for mod in pkg_resources.working_set}
if args.verbose:
    print("Installed modules: %s" % installed_modules)

# iterate over deps in reverse order, get rid of duplicates along the way
# also filter out Python packages that are already installed in current environment
res = []
handled = set()
for dep in reversed(deps):
    if dep not in handled:
        handled.add(dep)
        if dep[0] in installed_modules:
            if args.verbose:
                print("Skipping installed module '%s'" % dep[0])
        else:
            res.append(dep)

print("List of dependencies in (likely) install order:")
pprint(res, indent=4)
print("Sorted list of dependencies:")
pprint(sorted(res), indent=4)
