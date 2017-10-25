# -*- coding: utf-8 -*-
"""
Loader plugin support

Originally created for calmjs.rjs for handling requirejs loaders, this
ported version is stripped down to make it more generic so that other
frameworks may be able to extend on this.
"""

from __future__ import absolute_import

import logging
from os.path import exists
from os.path import join

from calmjs.npm import locate_package_entry_file
from calmjs.base import BaseRegistry
from calmjs.toolchain import WORKING_DIR

logger = logging.getLogger(__name__)


class LoaderPluginRegistry(BaseRegistry):

    def _init(self):
        for entry_point in self.raw_entry_points:
            try:
                cls = entry_point.load()
            except ImportError:
                logger.warning(
                    "registry '%s' failed to load loader plugin handler for "
                    "entry point '%s'", self.registry_name, entry_point,
                )
                continue

            if not issubclass(cls, BaseLoaderPluginHandler):
                logger.warning(
                    "entry point '%s' does not lead to a valid loader plugin "
                    "handler class", entry_point
                )
                continue

            try:
                inst = cls(self, entry_point.name)
            except Exception:
                logger.exception(
                    "the loader plugin class registered at '%s' failed "
                    "to be instantiated with the following exception",
                    entry_point,
                )
                continue

            if entry_point.name in self.records:
                old = type(self.records[entry_point.name])
                logger.warning(
                    "loader plugin handler for '%s' was already registered to "
                    "an instance of '%s:%s'; '%s' will now override this "
                    "registration",
                    entry_point.name, old.__module__, old.__name__, entry_point
                )
            self.records[entry_point.name] = inst

    def get_record(self, name):
        return self.records.get(name)


class BaseLoaderPluginHandler(object):
    """
    Generic loader plugin handler encapsulates the specific handling
    rules for a successful build; this includes dealing with injection
    of specific bundle sourcepaths and the like for the target framework
    to be supported by subclasses.
    """

    def __init__(self, registry, name=None):
        """
        The LoaderPluginRegistry will try to construct the instance and
        pass itself into the constructor; leaving this as the default
        will enable specific plugins to load further plugins should the
        input modname has more loader plugin strings.
        """

        self.registry = registry
        self.name = name

    def locate_bundle_sourcepath(self, toolchain, spec, plugin_sourcepath):
        """
        Subclasses must implement this to return a mapping of modnames
        the the absolute path of the desired sourcefiles.  Example:

        return {
            'text': '/tmp/src/example_module/text/index.js'
            'json': '/tmp/src/example_module/json/index.js'
        }

        Implementation must also accept both the toolchain and the spec
        argument, along with the plugin_sourcepath argument which will
        be a mapping of {modname: sourcepath} that are relevant to this
        specific plugin handler.  Instances of subclasses may then
        derive the the bundle_sourcepath required for a successful build
        for the given toolchain and spec.

        For nested/chained plugins, the recommended handling method is
        to also make use of the registry instance assigned to this
        handler instance to lookup specific handler(s) that may also
        be registered here, and use their locate_bundle_sourcepath
        method to generate the mapping required.
        """

        # default return value is an empty dictionary.
        return {}

    def strip_plugin(self, value):
        """
        Strip the first plugin fragment and return just the value.  This
        is a simple helper.  Note that the filter chaining can be very
        implementation specific to each and every loader plugin, so the
        default implementation is not going to attempt to consume
        everything in one go.
        """

        if value.startswith(self.name + '!'):
            result = value.split('!', 1)
            return result[-1]
        else:
            return value

    def __call__(self, toolchain, spec, modname, source, target, modpath):
        """
        These need to provide the actual implementation required for the
        production of the final artifact, so this will need to locate
        the resources needed for this set of arguments to function.

        Implementations must return the associated modpaths, targets, and
        the export_module_name as a 3-tuple, after the copying or
        transpilation step was done.  Example:

        return (
            {'text!text_file.txt': 'text!/some/path/text_file.txt'},
            {'text_file.txt': 'text_file.txt'},
            ['text!text_file.txt'],
        )

        Note that implementations can trigger further lookups through
        the registry instance attached to this instance of the plugin,
        and implementations must also address the handling of this
        lookup and usage of the return values.

        Also note that while the toolchain and spec arguments are also
        provided, they should only be used for lookups; out of band
        modifications results in convoluted code flow.
        """

        raise NotImplementedError


class NPMLoaderPluginHandler(BaseLoaderPluginHandler):
    """
    Encapsulates a loader plugin sourced from NPM (i.e. node_modules);
    this provides a framework to deal with path mangling and/or
    resolution for setting up the paths for usage within frameworks that
    provide support for loader plugins.
    """

    # The npm module name for this particular loader plugin.  If
    # specified, the default lookup method will attempt to locate this
    # the from the node_modules directory in current working directory.
    # Otherwise, it's assumed to be available (e.g. as part of the
    # exported JavaScript modules or specified to be bundled).

    node_module_pkg_name = None

    def locate_bundle_sourcepath(self, toolchain, spec, plugin_sourcepath):
        """
        Attempt to locate the plugin source; returns a mapping of
        modnames to the absolute path of the located sources.
        """

        if not self.node_module_pkg_name:
            return {}

        target = locate_package_entry_file(
            spec[WORKING_DIR], self.node_module_pkg_name)
        if target:
            logger.debug('picked %r for loader plugin %r', target, self.name)
            return {self.name: target}

        if exists(join(
                spec[WORKING_DIR], 'node_modules', self.node_module_pkg_name,
                'package.json')):
            logger.warning(
                "'package.json' for the npm package '%s' does not contain a "
                "valid entry point: sources required for loader plugin '%s' "
                "cannot be included automatically; the build process may fail",
                self.node_module_pkg_name, self.name,
            )
        else:
            logger.warning(
                "could not locate 'package.json' for the npm package '%s' "
                "which was specified to contain the loader plugin '%s' in the "
                "current working directory '%s'; the missing package may "
                "be installed by running 'npm install %s' for the mean time "
                "as a workaround, though the package that owns that source "
                "file that has this requirement should declare an explicit "
                "dependency; the build process may fail",
                self.node_module_pkg_name, self.name, spec[WORKING_DIR],
                self.node_module_pkg_name,
            )

        return {}
