# -*- coding: utf-8 -*-
"""
Module for the integration with distutils/setuptools.

Provides functions and classes that enable the management of npm
dependencies for JavaScript sources that lives in Python packages.
"""

from functools import partial
from logging import getLogger

from distutils.errors import DistutilsSetupError

from pkg_resources import Requirement
from pkg_resources import working_set as default_working_set

import json

logger = getLogger(__name__)

# default package definition filename.
DEFAULT_JSON = 'default.json'
EXTRAS_CALMJS_FIELD = 'extras_calmjs'
EXTRAS_CALMJS_JSON = 'extras_calmjs.json'
DEP_KEYS = ('dependencies', 'devDependencies')


def is_json_compat(value):
    """
    Check that the value is either a JSON decodable string or a dict
    that can be encoded into a JSON.

    Raises ValueError when validation fails.
    """

    try:
        value = json.loads(value)
    except ValueError as e:
        raise ValueError('JSON decoding error: ' + str(e))
    except TypeError:
        # Check that the value can be serialized back into json.
        try:
            json.dumps(value)
        except TypeError as e:
            raise ValueError(
                'must be a JSON serializable object: ' + str(e))

    if not isinstance(value, dict):
        raise ValueError(
            'must be specified as a JSON serializable dict or a '
            'JSON deserializable string'
        )

    return True


def validate_json_field(dist, attr, value):
    """
    Check for json validity.
    """

    try:
        is_json_compat(value)
    except ValueError as e:
        raise DistutilsSetupError("%r %s" % (attr, e))

    return True


def write_json_file(argname, cmd, basename, filename):
    """
    Write JSON captured from the defined argname into the package's
    egg-info directory using the specified filename.
    """

    value = getattr(cmd.distribution, argname, None)

    if isinstance(value, dict):
        value = json.dumps(
            value, indent=4, sort_keys=True, separators=(',', ': '))

    cmd.write_or_delete_file(argname, filename, value, force=True)


def get_pkg_dist(pkg_name, working_set=default_working_set):
    """
    Locate a package's distribution by its name.
    """

    req = Requirement.parse(pkg_name)
    return working_set.find(req)


def get_dist_egginfo_json(dist, filename=DEFAULT_JSON):
    """
    Safely get a json within an egginfo from a distribution.
    """

    # use the given package's istribution to acquire the json file.
    if not dist.has_metadata(filename):
        logger.debug("no '%s' for '%s'", filename, dist)
        return

    try:
        result = dist.get_metadata(filename)
    except IOError:
        logger.error("I/O error on reading of '%s' for '%s'.", filename, dist)
        return

    try:
        obj = json.loads(result)
    except (TypeError, ValueError):
        logger.error(
            "the '%s' found in '%s' is not a valid json.", filename, dist)
        return

    logger.debug("found '%s' for '%s'.", filename, dist)
    return obj


def read_egginfo_json(
        pkg_name, filename=DEFAULT_JSON, working_set=default_working_set):
    """
    Read json from egginfo of a package identified by `pkg_name` that's
    already installed within the current Python environment.
    """

    dist = get_pkg_dist(pkg_name, working_set=working_set)
    return get_dist_egginfo_json(dist, filename)


def iter_dist_requires(source_dist, working_set=default_working_set):
    """
    Generator to get requirements of a distribution.
    """

    requires = source_dist.requires() if source_dist else []
    # Go from the earliest package down to the latest one and apply it
    # to the callable 'f'
    for dist in reversed(working_set.resolve(requires)):
        yield dist


def flatten_dist_egginfo_json(
        source_dist, filename=DEFAULT_JSON, dep_keys=DEP_KEYS,
        working_set=default_working_set):
    """
    Flatten a distribution's egginfo json, with the depended keys to be
    flattened.

    Originally this was done for this:

    Resolve a distribution's (dev)dependencies through the working set
    and generate a flattened version package.json, returned as a dict,
    from the resolved distributions.

    Default working set is the one from pkg_resources.

    The generated package.json dict is done by grabbing all package.json
    metadata from all parent Python packages, starting from the highest
    level and down to the lowest.  The current distribution's
    dependencies will be layered on top along with its other package
    information.  This has the effect of child packages overriding
    node/npm dependencies which is by the design of this function.  If
    nested dependencies are desired, just rely on npm only for all
    dependency management.

    Flat is better than nested.
    """

    depends = {dep: {} for dep in dep_keys}

    # ensure that root is populated with something.
    if source_dist:
        root = get_dist_egginfo_json(source_dist, filename) or {}
    else:
        root = {}

    # Go from the earliest package down to the latest one, as we will
    # flatten children's d(evD)ependencies on top of parent's.
    for dist in iter_dist_requires(source_dist, working_set=working_set):
        obj = get_dist_egginfo_json(dist, filename)
        if not obj:
            continue

        logger.debug("merging '%s' for required '%s'", filename, dist)
        for dep in dep_keys:
            depends[dep].update(obj.get(dep, {}))

    if source_dist:
        # Layer original on top
        logger.debug("merging '%s' for target '%s'", filename, source_dist)
        for dep in dep_keys:
            depends[dep].update(root.get(dep, {}))

    for dep in dep_keys:
        # filtering out all the nulls.
        root[dep] = {k: v for k, v in depends[dep].items() if v is not None}

    return root


def flatten_egginfo_json(
        pkg_name, filename=DEFAULT_JSON, dep_keys=DEP_KEYS,
        working_set=default_working_set):
    """
    A shorthand calling convention where the package name is supplied
    instead of a distribution.

    Originally written for this:

    Generate a flattened package.json of a package `pkg_name` that's
    already installed within the current Python environment (defaults
    to the current global working_set which should have been set up
    correctly by pkg_resources).
    """

    dist = get_pkg_dist(pkg_name, working_set=working_set)
    return flatten_dist_egginfo_json(
        dist, filename=filename, dep_keys=dep_keys, working_set=working_set)


def flatten_extras(pkg_name, working_set=default_working_set):
    from calmjs.registry import get

    dep_keys = set(get('calmjs.extras_keys').iter_records())
    dist = get_pkg_dist(pkg_name, working_set=working_set)
    return flatten_dist_egginfo_json(
        dist, filename=EXTRAS_CALMJS_JSON,
        dep_keys=dep_keys, working_set=working_set
    )

write_extras_calmjs = partial(write_json_file, EXTRAS_CALMJS_FIELD)
