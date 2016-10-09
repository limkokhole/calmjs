# -*- coding: utf-8 -*-
import unittest
import json
import os
import sys
from argparse import ArgumentParser
from inspect import currentframe
from os.path import join
from os.path import exists
from logging import DEBUG
from logging import INFO

import pkg_resources

from calmjs import argparse as calmjs_argparse
from calmjs import cli
from calmjs import dist
from calmjs import runtime
from calmjs import toolchain
from calmjs.utils import pretty_logging
from calmjs.utils import which

from calmjs.testing import mocks
from calmjs.testing.utils import fake_error
from calmjs.testing.utils import make_dummy_dist
from calmjs.testing.utils import mkdtemp
from calmjs.testing.utils import remember_cwd
from calmjs.testing.utils import stub_item_attr_value
from calmjs.testing.utils import stub_base_which
from calmjs.testing.utils import stub_check_interactive
from calmjs.testing.utils import stub_mod_call
from calmjs.testing.utils import stub_stdin
from calmjs.testing.utils import stub_stdouts

which_npm = which('npm')


class BaseRuntimeTestCase(unittest.TestCase):

    def test_base_version(self):
        # The version information should be missing but shouldn't result
        # in catastrophic errors.
        stub_stdouts(self)
        rt = runtime.BaseRuntime()
        with self.assertRaises(SystemExit):
            rt(['-V'])
        out = sys.stdout.getvalue()
        self.doCleanups()
        self.assertEqual(out, 'no package information available.')

    def test_norm_args(self):
        stub_item_attr_value(self, sys, 'argv', ['script'])
        self.assertEqual(runtime.norm_args(None), [])
        self.assertEqual(runtime.norm_args([]), [])
        self.assertEqual(runtime.norm_args(['arg']), ['arg'])

        stub_item_attr_value(self, sys, 'argv', ['script', '-h'])
        self.assertEqual(runtime.norm_args(None), ['-h'])
        self.assertEqual(runtime.norm_args([]), [])
        self.assertEqual(runtime.norm_args(['arg']), ['arg'])

    def test_global_flags(self):
        stub_stdouts(self)
        bt = runtime.BaseRuntime()
        bt(['-vvv', '-qq', '-d'])

        # should be a global state.
        rt = runtime.BaseRuntime()
        self.assertEqual(rt.verbosity, 1)
        self.assertEqual(rt.debug, 1)
        self.assertEqual(rt.log_level, INFO)


class ToolchainRuntimeTestCase(unittest.TestCase):
    """
    Test cases for the toolchain runtime.
    """

    def test_toolchain_runtime_basic_config(self):
        tc = toolchain.NullToolchain()
        rt = runtime.ToolchainRuntime(tc)
        text = rt.argparser.format_help()
        self.assertIn(
            "--build-dir", text,
        )

        self.assertTrue(isinstance(rt.create_spec(), toolchain.Spec))

    def test_standard_run(self):
        tc = toolchain.NullToolchain()
        rt = runtime.ToolchainRuntime(tc)

        err = mocks.StringIO()
        with pretty_logging(logger='calmjs.runtime', level=DEBUG, stream=err):
            result = rt.run(export_target='dummy')
        self.assertTrue(isinstance(result, toolchain.Spec))
        # prove that it did at least run
        self.assertIn('build_dir', result)

    def test_basic_execution(self):
        stub_stdouts(self)
        tc = toolchain.NullToolchain()
        rt = runtime.ToolchainRuntime(tc)
        result = rt(['--export-target=dummy'])
        # as result returned not defined for these lower level runtimes
        # not registered as console entry points, any result can be
        # returned.
        self.assertTrue(isinstance(result, toolchain.Spec))
        # prove that it did at least run
        self.assertIn('build_dir', result)
        self.assertEqual(result['link'], 'linked')

    def test_prompt_export_target_export_target_undefined(self):
        stub_stdouts(self)
        spec = toolchain.Spec()
        rt = runtime.ToolchainRuntime(toolchain.NullToolchain())
        with self.assertRaises(toolchain.ToolchainAbort):
            rt.prompt_export_target_check(spec)

    def test_prompt_export_target_check_not_exists(self):
        stub_stdouts(self)
        target_dir = mkdtemp(self)
        export_target = join(target_dir, 'export_file')
        spec = toolchain.Spec(export_target=export_target)
        rt = runtime.ToolchainRuntime(toolchain.NullToolchain())
        rt.prompt_export_target_check(spec)
        self.assertEqual(sys.stdout.getvalue(), '')

    def test_prompt_export_target_check_exists_no(self):
        stub_check_interactive(self, True)
        stub_stdouts(self)
        stub_stdin(self, u'n\n')
        target_dir = mkdtemp(self)
        export_target = join(target_dir, 'export_file')
        open(export_target, 'w').close()  # write an empty file
        spec = toolchain.Spec(export_target=export_target)
        rt = runtime.ToolchainRuntime(toolchain.NullToolchain())
        with self.assertRaises(toolchain.ToolchainCancel):
            rt.prompt_export_target_check(spec)
        self.assertIn('already exists, overwrite?', sys.stdout.getvalue())

    def test_prompt_export_target_check_exists_yes(self):
        stub_check_interactive(self, True)
        stub_stdouts(self)
        stub_stdin(self, u'y\n')
        target_dir = mkdtemp(self)
        export_target = join(target_dir, 'export_file')
        open(export_target, 'w').close()  # write an empty file
        spec = toolchain.Spec(export_target=export_target)
        rt = runtime.ToolchainRuntime(toolchain.NullToolchain())
        rt.prompt_export_target_check(spec)
        self.assertIn('already exists, overwrite?', sys.stdout.getvalue())

    def test_prompt_export_target_check_exists_non_interactive(self):
        stub_check_interactive(self, False)
        stub_stdouts(self)
        stub_stdin(self, u'y\n')
        target_dir = mkdtemp(self)
        export_target = join(target_dir, 'export_file')
        open(export_target, 'w').close()  # write an empty file
        spec = toolchain.Spec(export_target=export_target)
        rt = runtime.ToolchainRuntime(toolchain.NullToolchain())
        with pretty_logging(
                logger='calmjs', level=DEBUG, stream=mocks.StringIO()) as err:
            with self.assertRaises(toolchain.ToolchainCancel):
                rt.prompt_export_target_check(spec)
        self.assertIn(
            'non-interactive mode; auto-selecting default option [No]',
            err.getvalue()
        )

    def test_prompted_execution_exists(self):
        stub_check_interactive(self, True)
        stub_stdouts(self)
        stub_stdin(self, u'y\n')

        target_dir = mkdtemp(self)
        export_target = join(target_dir, 'export_file')
        open(export_target, 'w').close()  # write an empty file

        tc = toolchain.NullToolchain()
        rt = runtime.ToolchainRuntime(tc)
        result = rt(['--export-target', export_target])
        self.assertIn(
            "export target '%s' already exists, overwrite? " % export_target,
            sys.stdout.getvalue()
        )
        self.assertNotIn('CRITICAL', sys.stdout.getvalue())
        self.assertTrue(isinstance(result, toolchain.Spec))
        # prove that it did at least run
        self.assertIn('build_dir', result)
        self.assertEqual(result['link'], 'linked')

    def test_prompted_execution_exists_overwrite(self):
        stub_check_interactive(self, True)
        stub_stdouts(self)
        stub_stdin(self, u'y\n')

        target_dir = mkdtemp(self)
        export_target = join(target_dir, 'export_file')
        open(export_target, 'w').close()  # write an empty file

        tc = toolchain.NullToolchain()
        rt = runtime.ToolchainRuntime(tc)
        result = rt(['--export-target', export_target, '-w'])
        self.assertNotIn(
            "export target '%s' already exists, overwrite? " % export_target,
            sys.stdout.getvalue()
        )
        self.assertNotIn('CRITICAL', sys.stdout.getvalue())
        self.assertTrue(isinstance(result, toolchain.Spec))
        # prove that it did at least run
        self.assertIn('build_dir', result)
        self.assertEqual(result['link'], 'linked')

    def test_prompted_execution_exists_cancel(self):
        stub_check_interactive(self, True)
        stub_stdouts(self)
        stub_stdin(self, u'n\n')

        target_dir = mkdtemp(self)
        export_target = join(target_dir, 'export_file')
        open(export_target, 'w').close()  # write an empty file

        tc = toolchain.NullToolchain()
        rt = runtime.ToolchainRuntime(tc)
        result = rt(['--export-target', export_target])
        self.assertIn(
            "export target '%s' already exists, overwrite? " % export_target,
            sys.stdout.getvalue()
        )
        self.assertNotIn('CRITICAL', sys.stdout.getvalue())
        self.assertTrue(isinstance(result, toolchain.Spec))
        # prove that the cancel really happened.
        self.assertIn('build_dir', result)
        self.assertNotIn('link', result)

        # Should not have unexpected error logged.
        stderr = sys.stderr.getvalue()
        self.assertNotIn(
            "an event in group 'after_prepare' triggered an abort: "
            "EXPORT_TARGET should be specified by this stage", stderr,
        )
        self.assertNotIn(
            "terminating due to expected unrecoverable condition",
            stderr,
        )

    def test_excution_missing_export_file(self):
        # as the null toolchain does not automatically provide one
        stub_stdouts(self)
        rt = runtime.ToolchainRuntime(toolchain.NullToolchain())
        result = rt([])
        self.assertEqual('', sys.stdout.getvalue())
        stderr = sys.stderr.getvalue()
        self.assertIn('CRITICAL', stderr)
        # no direct error message logged by the BaseRuntime.__call__
        self.assertNotIn('CRITICAL: ToolchainAbort:', stderr)
        self.assertIn(
            "an event in group 'after_prepare' triggered an abort: "
            "EXPORT_TARGET should be specified by this stage", stderr,
        )
        self.assertIn(
            "terminating due to expected unrecoverable condition",
            stderr,
        )

        self.assertFalse(result)

    def test_spec_nodebug(self):
        tc = toolchain.NullToolchain()
        rt = runtime.ToolchainRuntime(tc)
        result = rt(['--export-target', 'dummy'])
        self.assertEqual(result['debug'], 0)

    def test_spec_debugged(self):
        tc = toolchain.NullToolchain()
        rt = runtime.ToolchainRuntime(tc)
        result = rt(['-dd', '--export-target', 'dummy'])
        self.assertEqual(result['debug'], 2)

    def test_spec_debugged_via_cmdline(self):
        stub_item_attr_value(
            self, mocks, 'dummy',
            runtime.ToolchainRuntime(toolchain.NullToolchain()),
        )
        working_set = mocks.WorkingSet({
            'calmjs.runtime': [
                'tool = calmjs.testing.mocks:dummy',
            ],
        })
        rt = runtime.Runtime(working_set=working_set, prog='calmjs')
        result = rt(['tool', '--export-target', 'dummy', '-d'])
        self.assertEqual(result['debug'], 1)

    @unittest.skipIf(currentframe() is None, 'stack frame not supported')
    def test_spec_debugged_via_cmdline_target_exists_export_cancel(self):
        stub_item_attr_value(
            self, mocks, 'dummy',
            runtime.ToolchainRuntime(toolchain.NullToolchain()),
        )
        working_set = mocks.WorkingSet({
            'calmjs.runtime': [
                'tool = calmjs.testing.mocks:dummy',
            ],
        })
        tmpdir = mkdtemp(self)
        target = join(tmpdir, 'target')
        open(target, 'w').close()
        rt = runtime.Runtime(working_set=working_set, prog='calmjs')
        stub_stdouts(self)
        stub_stdin(self, u'n\n')
        stub_check_interactive(self, True)
        result = rt(['tool', '--export-target', target, '-dd', '-vv'])
        self.assertEqual(result['debug'], 2)
        # This is an integration test of sort for the debug event output
        self.assertIn("on_event 'cleanup' invoked by", sys.stderr.getvalue())
        self.assertIn("toolchain.py", sys.stderr.getvalue())
        self.assertIn(
            'on_event(AFTER_PREPARE, self.prompt_export_target_check, spec)',
            sys.stderr.getvalue(),
        )


class PackageManagerDriverTestCase(unittest.TestCase):
    """
    Test cases for the package manager driver and argparse usage.
    """

    def test_command_creation(self):
        driver = cli.PackageManagerDriver(pkg_manager_bin='mgr')
        cmd = runtime.PackageManagerRuntime(driver)
        text = cmd.argparser.format_help()
        self.assertIn(
            "run 'mgr install' with generated 'default.json';", text,
        )

    def test_duplicate_init_no_error(self):
        driver = cli.PackageManagerDriver(pkg_manager_bin='mgr')
        cmd = runtime.PackageManagerRuntime(driver)
        cmd.init()

    def test_root_runtime_errors_ignored(self):
        stub_stdouts(self)
        working_set = mocks.WorkingSet({'calmjs.runtime': [
            'foo = calmjs.nosuchmodule:no.where',
            'bar = calmjs.npm:npm',
            'npm = calmjs.npm:npm.runtime',
        ]})
        rt = runtime.Runtime(working_set=working_set)
        with self.assertRaises(SystemExit):
            rt(['-h'])
        out = sys.stdout.getvalue()
        self.assertNotIn('foo', out)
        self.assertIn('npm', out)

    def test_root_runtime_bad_names(self):
        working_set = mocks.WorkingSet({'calmjs.runtime': [
            'bad name = calmjs.npm:npm.runtime',
            'bad.name = calmjs.npm:npm.runtime',
            'badname:likethis = calmjs.npm:npm.runtime',
        ]})

        stderr = mocks.StringIO()
        with pretty_logging(
                logger='calmjs.runtime', level=DEBUG, stream=stderr):
            rt = runtime.Runtime(working_set=working_set)
        err = stderr.getvalue()

        self.assertIn("bad 'calmjs.runtime' entry point", err)

        stub_stdouts(self)
        with self.assertRaises(SystemExit):
            rt(['-h'])
        out = sys.stdout.getvalue()
        # this results in unnatural argparsing situation
        self.assertNotIn('bad name', out)
        # reserved for disambiguation
        self.assertNotIn('bad.name', out)
        self.assertNotIn('badname:likethis', out)
        # command listing naturally not available.
        self.assertNotIn('npm', out)

    def setup_dupe_runtime(self):
        from calmjs.testing import utils
        from calmjs.npm import npm
        utils.foo_runtime = runtime.PackageManagerRuntime(npm.cli_driver)
        utils.runtime_foo = runtime.PackageManagerRuntime(npm.cli_driver)

        def cleanup():
            del utils.foo_runtime
            del utils.runtime_foo
        self.addCleanup(cleanup)

    def test_duplication_and_runtime_errors(self):
        """
        Duplicated entry point names

        Naturally, there may be situations where different packages have
        registered entry_points with the same name.  It will be great if
        that can be addressed.
        """

        self.setup_dupe_runtime()

        make_dummy_dist(self, ((
            'entry_points.txt',
            '[calmjs.runtime]\n'
            'bar = calmjs.testing.utils:foo_runtime\n'
        ),), 'example1.foo', '1.0')

        make_dummy_dist(self, ((
            'entry_points.txt',
            '[calmjs.runtime]\n'
            'bar = calmjs.testing.utils:foo_runtime\n'
        ),), 'example2.foo', '1.0')

        make_dummy_dist(self, ((
            'entry_points.txt',
            '[calmjs.runtime]\n'
            'bar = calmjs.testing.utils:runtime_foo\n'
            'baz = calmjs.testing.utils:runtime_foo\n'
        ),), 'example3.foo', '1.0')

        make_dummy_dist(self, ((
            'entry_points.txt',
            '[calmjs.runtime]\n'
            'bar = calmjs.testing.utils:runtime_foo\n'
            'baz = calmjs.testing.utils:runtime_foo\n'
        ),), 'example4.foo', '1.0')

        working_set = pkg_resources.WorkingSet([self._calmjs_testing_tmpdir])

        stderr = mocks.StringIO()
        with pretty_logging(
                logger='calmjs.runtime', level=DEBUG, stream=stderr):
            rt = runtime.Runtime(working_set=working_set)

        msg = stderr.getvalue()
        self.assertIn(
            "duplicated registration of command 'baz' via entry point "
            "'baz = calmjs.testing.utils:runtime_foo' ignored; ",
            msg
        )
        self.assertIn(
            "a calmjs runtime command named 'bar' already registered.", msg)
        self.assertIn(
            "'bar = calmjs.testing.utils:foo_runtime' from 'example", msg)
        self.assertIn(
            "'bar = calmjs.testing.utils:runtime_foo' from 'example", msg)
        # Registration order is non-deterministic, so fallback is too
        self.assertIn("fallback command 'calmjs.testing.utils:", msg)
        self.assertIn("is already registered.", msg)

        # Try to use it
        stub_stdouts(self)
        with self.assertRaises(SystemExit):
            rt(['-h'])
        out = sys.stdout.getvalue()
        self.assertIn('bar', out)
        self.assertIn('baz', out)

        # Both fallbacks should be registered, to ensure disambiguation,
        # as the load order can be influenced randomly by dict ordering
        # or even the filesystem file load order.
        foo_runtime = 'calmjs.testing.utils:foo_runtime'
        runtime_foo = 'calmjs.testing.utils:runtime_foo'
        self.assertIn(runtime_foo, out)
        self.assertIn(foo_runtime, out)

        # see that the full one can be invoked and actually invoke the
        # underlying runtime
        stub_stdouts(self)
        with self.assertRaises(SystemExit):
            rt([foo_runtime, '-h'])
        out = sys.stdout.getvalue()
        self.assertIn(foo_runtime, out)
        self.assertIn("run 'npm install' with generated 'package.json';", out)

        stub_stdouts(self)
        with self.assertRaises(SystemExit):
            rt([runtime_foo, '-h'])
        out = sys.stdout.getvalue()
        self.assertIn(runtime_foo, out)
        self.assertIn("run 'npm install' with generated 'package.json';", out)

        # Time to escalate the problems one can cause...
        with self.assertRaises(RuntimeError):
            # yeah instances of root runtimes are NOT meant for reuse
            # by other runtime instances or argparsers, so this will
            # fail.
            rt.init_argparser(ArgumentParser())

        stderr = mocks.StringIO()
        with pretty_logging(
                logger='calmjs.runtime', level=DEBUG, stream=stderr):
            rt.argparser = None
            rt.init()

        # A forced reinit shouldn't cause a major issue, but it will
        # definitely result in a distinct lack of named commands.
        self.assertNotIn(
            "Runtime instance has been used or initialized improperly.", msg)

        stub_stdouts(self)
        with self.assertRaises(SystemExit):
            rt(['-h'])
        out = sys.stdout.getvalue()
        self.assertNotIn('bar', out)
        self.assertNotIn('baz', out)

        # Now for the finale, where we really muck with the internals.
        stderr = mocks.StringIO()
        with pretty_logging(
                logger='calmjs.runtime', level=DEBUG, stream=stderr):
            # This normally shouldn't happen due to naming restriction,
            # i.e. where names with "." or ":" are disallowed so that
            # they are reserved for fallbacks; although if some other
            # forces are at work, like this...
            rt.runtimes[foo_runtime] = runtime.DriverRuntime(None)
            rt.runtimes[runtime_foo] = runtime.DriverRuntime(None)
            # Now, if one were to force a bad init to happen with
            # (hopefully forcibly) mismatched runtime instances, the
            # main runtime instance will simply explode into the logger
            # in a fit of critical level agony.
            rt.argparser = None
            rt.init()

        # EXPLOSION
        msg = stderr.getvalue()
        self.assertIn("CRITICAL", msg)
        self.assertIn(
            "Runtime instance has been used or initialized improperly.", msg)
        # Naisu Bakuretsu - Megumin.


class ArgumentHandlingTestCase(unittest.TestCase):
    """
    The runtime uses argparser with subparsers underneath and argparser
    does not generate useful error messages if it doesn't actually track
    where the bad flags actually got raised.  Here are some of the cases
    that need checking.
    """

    known_cmd = 'cmd'

    def setUp(self):
        stub_stdouts(self)

    def setup_runtime(self):
        # create a working set with our custom runtime entry point
        # TODO should really improve the test case to provide custom
        # runtime instances separate from actual data.
        working_set = mocks.WorkingSet({
            'calmjs.runtime': [
                'cmd = calmjs.npm:npm.runtime',
            ],
        })
        return runtime.Runtime(working_set=working_set, prog='calmjs')

    # for the test, we use the -u flag for the unknown tests as it is
    # unknown to bootstrap and target parser.  Next two are using known
    # flag to before, then after.

    def test_before_extras(self):
        rt = self.setup_runtime()
        with self.assertRaises(SystemExit):
            rt(['-u', 'cmd', 'pkg'])
        err = sys.stderr.getvalue().splitlines()[-1].strip()
        self.assertEqual("calmjs: error: unrecognized arguments: -u", err)

    def test_after_extras(self):
        rt = self.setup_runtime()
        with self.assertRaises(SystemExit):
            rt(['cmd', 'pkg', '-u'])
        err = sys.stderr.getvalue().splitlines()[-1].strip()
        self.assertEqual("calmjs cmd: error: unrecognized arguments: -u", err)

    def test_before_and_after_extras(self):
        rt = self.setup_runtime()
        with self.assertRaises(SystemExit):
            rt(['-u', 'cmd', 'pkg', '-u'])
        err = sys.stderr.getvalue().splitlines()[-1].strip()
        # former has priority
        self.assertEqual("calmjs: error: unrecognized arguments: -u", err)

    def test_before_known_and_after_unknown(self):
        rt = self.setup_runtime()
        with self.assertRaises(SystemExit):
            rt(['-v', 'cmd', 'pkg', '-u'])
        err = sys.stderr.getvalue().splitlines()[-1].strip()
        self.assertEqual("calmjs cmd: error: unrecognized arguments: -u", err)

    def test_before_and_after_extras_scattered(self):
        # previously test_before_and_after_extras_known_before, as
        # scattering the -v after will not work.  Since the bootstrap
        # picks up that anyway, might as well force global enablement of
        # this flag.
        rt = self.setup_runtime()
        rt(['-v', 'cmd', 'pkg', '-v'])
        self.assertEqual(rt.log_level, DEBUG)
        err = sys.stderr.getvalue().splitlines()[-1].strip()
        self.assertIn("generating a flattened 'package.json' for 'pkg'", err)

    def test_before_and_after_extras_known_after(self):
        rt = self.setup_runtime()
        with self.assertRaises(SystemExit):
            rt(['-i', 'cmd', 'pkg', '-i'])
        err = sys.stderr.getvalue().splitlines()[-1].strip()
        self.assertEqual("calmjs: error: unrecognized arguments: -i", err)

    # other sanity/behavior verification tests

    def test_before_and_after_extras_known_after_missing_arg(self):
        rt = self.setup_runtime()
        with self.assertRaises(SystemExit):
            rt(['-i', 'cmd', '-i'])
        err = sys.stderr.getvalue().splitlines()[-1].strip()
        # exact message differs between py2 and py3
        self.assertIn("calmjs cmd: error: ", err)


class PackageManagerRuntimeAlternativeIntegrationTestCase(unittest.TestCase):
    """
    A comprehensive integration based on a customized environment for
    testing functionality requirements between changes in 1.0 and 2.0,
    where the cli interactive stuff is moved to runtime.  This series of
    tests is based on what were cli unit tests but now those features
    are provided by the runtime.
    """

    def setup_runtime(self):
        stub_stdouts(self)
        remember_cwd(self)
        cwd = mkdtemp(self)
        os.chdir(cwd)
        make_dummy_dist(self, (
            ('requirements.json', json.dumps({
                'name': 'calmpy.pip',
                'require': {
                    'setuptools': '25.1.6',
                },
            })),
        ), 'calmpy.pip', '2.0')

        make_dummy_dist(self, (
            ('requires.txt', '[dev]\ncalmpy.pip'),
        ), 'site', '1.0')

        working_set = pkg_resources.WorkingSet([self._calmjs_testing_tmpdir])

        # Stub out the underlying data needed for the cli for the tests
        # to test against our custom data for reproducibility.
        stub_item_attr_value(self, dist, 'default_working_set', working_set)
        stub_check_interactive(self, True)
        driver = cli.PackageManagerDriver(
            pkg_manager_bin='mgr', pkgdef_filename='requirements.json',
            dep_keys=('require',),
        )
        return cwd, runtime.PackageManagerRuntime(driver)

    # do note: the runtime is not registered to the root runtime
    # directly, but this is a good enough emulation on how this would
    # behave under real circumstances, as each of these runtime can and
    # should be able to operate as independent entities.

    def test_pkg_manager_view(self):
        cwd, runtime = self.setup_runtime()
        result = runtime.cli_driver.pkg_manager_view('calmpy.pip')
        self.assertEqual(result, {
            "require": {"setuptools": "25.1.6"},
            "name": "calmpy.pip",
        })
        runtime(['calmpy.pip'])
        result2 = json.loads(sys.stdout.getvalue().strip())
        self.assertEqual(result, result2)

    def test_pkg_manager_init(self):
        cwd, runtime = self.setup_runtime()
        runtime(['--init', 'calmpy.pip'])
        target = join(cwd, 'requirements.json')
        self.assertTrue(exists(target))
        with open(target) as fd:
            result = json.load(fd)
        self.assertEqual(result, {
            "require": {"setuptools": "25.1.6"},
            "name": "calmpy.pip",
        })

    def test_pkg_manager_init_exists_and_overwrite(self):
        cwd, runtime = self.setup_runtime()
        target = join(cwd, 'requirements.json')

        with open(target, 'w') as fd:
            result = json.dump({"require": {"unrelated": "1.2.3"}}, fd)

        runtime(['--init', 'calmpy.pip'])
        stderr = sys.stderr.getvalue()

        self.assertIn('not overwriting existing ', stderr)
        self.assertIn('requirements.json', stderr)

        with open(target) as fd:
            result = json.load(fd)
        self.assertNotEqual(result, {"require": {"setuptools": "25.1.6"}})

        runtime(['--init', 'calmpy.pip', '--overwrite'])
        with open(target) as fd:
            result = json.load(fd)
        self.assertEqual(result, {
            "require": {"setuptools": "25.1.6"},
            "name": "calmpy.pip",
        })

    def test_pkg_manager_init_overwrite_interactive(self):
        cwd, runtime = self.setup_runtime()
        target = join(cwd, 'requirements.json')
        with open(target, 'w') as fd:
            result = json.dump({"require": {"unrelated": "1.2.3"}}, fd)

        stub_stdin(self, u'n\n')
        runtime(['--init', 'calmpy.pip', '-i'])
        stdout = sys.stdout.getvalue()
        self.assertIn("differs with ", stdout)
        self.assertIn("Overwrite", stdout)
        self.assertIn("requirements.json'?", stdout)
        with open(target) as fd:
            result = json.load(fd)
        self.assertNotEqual(result, {
            "require": {"setuptools": "25.1.6"},
            "name": "calmpy.pip",
        })

        stub_stdin(self, u'y\n')
        runtime(['--init', 'calmpy.pip', '-i'])
        stdout = sys.stdout.getvalue()
        self.assertIn("differs with ", stdout)
        self.assertIn("Overwrite", stdout)
        self.assertIn("requirements.json'?", stdout)
        with open(target) as fd:
            result = json.load(fd)
        self.assertEqual(result, {
            "require": {"setuptools": "25.1.6"},
            "name": "calmpy.pip",
        })

    def test_pkg_manager_init_merge_interactive(self):
        cwd, runtime = self.setup_runtime()
        target = join(cwd, 'requirements.json')
        with open(target, 'w') as fd:
            result = json.dump({"require": {"unrelated": "1.2.3"}}, fd)

        stub_stdin(self, u'y\n')
        runtime(['--init', 'calmpy.pip', '-i', '-m'])
        stdout = sys.stdout.getvalue()
        self.assertIn("differs with ", stdout)
        self.assertIn("Overwrite", stdout)
        self.assertIn("requirements.json'?", stdout)
        with open(target) as fd:
            result = json.load(fd)
        self.assertEqual(result, {
            "require": {"setuptools": "25.1.6", "unrelated": "1.2.3"},
            "name": "calmpy.pip",
        })

    def test_pkg_manager_view_extras(self):
        cwd, runtime = self.setup_runtime()
        runtime(['site'])
        result = json.loads(sys.stdout.getvalue().strip())
        self.assertEqual(result, {
            "require": {},
            "name": "site",
        })

        stub_stdouts(self)
        runtime(['site[dev]'])
        result = json.loads(sys.stdout.getvalue().strip())
        self.assertEqual(result, {
            "require": {"setuptools": "25.1.6"},
            "name": "site[dev]",
        })

    def test_pkg_manager_view_malformed(self):
        cwd, runtime = self.setup_runtime()
        runtime(['[dev]'])
        self.assertIn(
            'ValueError: malformed package name(s) specified: [dev]',
            sys.stderr.getvalue(),
        )


@unittest.skipIf(which_npm is None, 'npm not found.')
class RuntimeIntegrationTestCase(unittest.TestCase):

    def setup_runtime(self):
        make_dummy_dist(self, (
            ('package.json', json.dumps({
                'name': 'site',
                'dependencies': {
                    'jquery': '~3.1.0',
                },
            })),
        ), 'example.package1', '1.0')

        make_dummy_dist(self, (
            ('package.json', json.dumps({
                'name': 'site',
                'dependencies': {
                    'underscore': '~1.8.3',
                },
            })),
        ), 'example.package2', '2.0')

        make_dummy_dist(self, (
            ('requires.txt', '\n'.join([
                'example.package1',
                'example.package2',
            ])),
            ('package.json', json.dumps({
                'dependencies': {
                    'backbone': '~1.3.2',
                },
            })),
        ), 'example.package3', '2.0')

        working_set = pkg_resources.WorkingSet([self._calmjs_testing_tmpdir])

        # Stub out the underlying data needed for the cli for the tests
        # to test against our custom data for reproducibility.
        stub_item_attr_value(self, dist, 'default_working_set', working_set)
        stub_check_interactive(self, True)

        # Of course, apply a mock working set for the runtime instance
        # so it can use the npm runtime, however we will use a different
        # keyword.  Note that the runtime is invoked using foo.
        working_set = mocks.WorkingSet({
            'calmjs.runtime': [
                'foo = calmjs.npm:npm.runtime',
            ],
        })
        return runtime.Runtime(working_set=working_set)

    def test_npm_init_integration(self):
        remember_cwd(self)
        tmpdir = mkdtemp(self)
        os.chdir(tmpdir)

        rt = self.setup_runtime()
        rt(['foo', '--init', 'example.package1'])

        with open(join(tmpdir, 'package.json')) as fd:
            result = json.load(fd)

        self.assertEqual(result['dependencies']['jquery'], '~3.1.0')

    def test_npm_install_integration(self):
        remember_cwd(self)
        tmpdir = mkdtemp(self)
        os.chdir(tmpdir)
        stub_mod_call(self, cli)
        stub_base_which(self, which_npm)
        rt = self.setup_runtime()
        rt(['foo', '--install', 'example.package1', 'example.package2'])

        with open(join(tmpdir, 'package.json')) as fd:
            result = json.load(fd)

        self.assertEqual(result['dependencies']['jquery'], '~3.1.0')
        self.assertEqual(result['dependencies']['underscore'], '~1.8.3')
        # not foo install, but npm install since entry point specified
        # the actual runtime instance.
        self.assertEqual(self.call_args, (([which_npm, 'install'],), {}))

    def test_npm_view(self):
        stub_stdouts(self)
        rt = self.setup_runtime()
        rt(['foo', '--view', 'example.package1', 'example.package2'])
        result = json.loads(sys.stdout.getvalue())
        self.assertEqual(result['dependencies']['jquery'], '~3.1.0')
        self.assertEqual(result['dependencies']['underscore'], '~1.8.3')

        stub_stdouts(self)
        rt(['foo', 'example.package1', 'example.package2'])
        result = json.loads(sys.stdout.getvalue())
        self.assertEqual(result['dependencies']['jquery'], '~3.1.0')
        self.assertEqual(result['dependencies']['underscore'], '~1.8.3')

    def test_npm_view_dependencies(self):
        stub_stdouts(self)
        rt = self.setup_runtime()
        rt(['foo', 'example.package3'])
        result = json.loads(sys.stdout.getvalue())
        self.assertEqual(result['dependencies'], {
            'jquery': '~3.1.0',
            'underscore': '~1.8.3',
            'backbone': '~1.3.2',
        })

        stub_stdouts(self)
        rt(['foo', 'example.package3', '-E'])
        result = json.loads(sys.stdout.getvalue())
        self.assertEqual(result['dependencies'], {
            'backbone': '~1.3.2',
        })

        stub_stdouts(self)
        rt(['foo', 'example.package3', 'example.package2', '--explicit'])
        result = json.loads(sys.stdout.getvalue())
        self.assertEqual(result['dependencies'], {
            'backbone': '~1.3.2',
            'underscore': '~1.8.3',
        })

    def test_npm_all_the_actions(self):
        remember_cwd(self)
        tmpdir = mkdtemp(self)
        os.chdir(tmpdir)
        stub_stdouts(self)
        stub_mod_call(self, cli)
        stub_base_which(self, which_npm)
        rt = self.setup_runtime()
        rt(['foo', '--install', '--view', '--init',
            'example.package1', 'example.package2'])

        # inside stdout
        result = json.loads(sys.stdout.getvalue())
        self.assertEqual(result['dependencies']['jquery'], '~3.1.0')
        self.assertEqual(result['dependencies']['underscore'], '~1.8.3')

        with open(join(tmpdir, 'package.json')) as fd:
            result = json.load(fd)

        self.assertEqual(result['dependencies']['jquery'], '~3.1.0')
        self.assertEqual(result['dependencies']['underscore'], '~1.8.3')
        # not foo install, but npm install since entry point specified
        # the actual runtime instance.
        self.assertEqual(self.call_args, (([which_npm, 'install'],), {}))

    def test_npm_verbose_quiet(self):
        remember_cwd(self)
        tmpdir = mkdtemp(self)
        os.chdir(tmpdir)
        rt = self.setup_runtime()

        stub_stdouts(self)
        rt(['-v', 'foo', '--init', 'example.package1'])
        self.assertIn("generating a flattened", sys.stderr.getvalue())
        self.assertNotIn("found 'package.json'", sys.stderr.getvalue())

        # extra verbosity shouldn't blow up
        stub_stdouts(self)
        rt(['-vvvv', 'foo', '--init', 'example.package1'])
        self.assertIn("generating a flattened", sys.stderr.getvalue())
        self.assertIn("found 'package.json'", sys.stderr.getvalue())

        # q and v negates each other
        stub_stdouts(self)
        rt(['-v', '-q', 'foo', '--init', 'example.package2'])
        self.assertNotIn("generating a flattened", sys.stderr.getvalue())
        self.assertNotIn("found 'package.json'", sys.stderr.getvalue())
        self.assertIn("WARNING", sys.stderr.getvalue())

        # extra quietness shouldn't blow up
        stub_stdouts(self)
        rt(['-qqqqq', 'foo', '--install', 'example.package2'])
        self.assertNotIn("WARNING", sys.stderr.getvalue())

    def test_npm_init_existing_malform(self):
        remember_cwd(self)
        tmpdir = mkdtemp(self)
        os.chdir(tmpdir)
        rt = self.setup_runtime()

        # create an existing malformed file
        with open(join(tmpdir, 'package.json'), 'w') as fd:
            fd.write('not a json')
        stub_stdouts(self)
        rt(['foo', '--init', 'example.package2'])
        self.assertIn("ignoring existing malformed", sys.stderr.getvalue())

    def test_npm_interrupted(self):
        remember_cwd(self)
        tmpdir = mkdtemp(self)
        os.chdir(tmpdir)
        rt = self.setup_runtime()

        stub_stdouts(self)
        # ensure the binary is not found.
        stub_mod_call(self, cli, fake_error(KeyboardInterrupt))
        rt(['foo', '--install', 'example.package2'])
        self.assertIn("CRITICAL", sys.stderr.getvalue())
        self.assertIn(
            "termination requested; aborted.", sys.stderr.getvalue())

    def test_npm_binary_not_found(self):
        remember_cwd(self)
        tmpdir = mkdtemp(self)
        os.chdir(tmpdir)
        rt = self.setup_runtime()

        stub_stdouts(self)
        # ensure the binary is not found.
        stub_mod_call(self, cli, fake_error(IOError))
        rt(['foo', '--install', 'example.package2'])
        self.assertIn("ERROR", sys.stderr.getvalue())
        self.assertIn(
            "invocation of the 'npm' binary failed;", sys.stderr.getvalue())

    def test_npm_binary_not_found_debug(self):
        remember_cwd(self)
        tmpdir = mkdtemp(self)
        os.chdir(tmpdir)
        rt = self.setup_runtime()
        stub_stdouts(self)

        # ensure the binary is not found.
        stub_mod_call(self, cli, fake_error(IOError))
        rt(['-d', 'foo', '--install', 'example.package2'])
        stderr = sys.stderr.getvalue()
        self.assertIn("ERROR", stderr)
        self.assertIn(
            "invocation of the 'npm' binary failed;", stderr)
        self.assertIn("terminating due to unexpected exception", stderr)
        self.assertIn("Traceback ", stderr)
        self.assertNotIn("(Pdb)", stderr)

    def test_npm_binary_not_found_debugger(self):
        from calmjs import utils

        def fake_post_mortem(*a, **kw):
            sys.stdout.write('(Pdb) ')

        remember_cwd(self)
        tmpdir = mkdtemp(self)
        os.chdir(tmpdir)
        rt = self.setup_runtime()
        # stub_stdin(self, u'quit\n')
        stub_stdouts(self)

        # ensure the binary is not found.
        stub_mod_call(self, cli, fake_error(IOError))
        stub_item_attr_value(self, utils, 'post_mortem', fake_post_mortem)
        rt(['-dd', 'foo', '--install', 'example.package2'])

        stderr = sys.stderr.getvalue()
        self.assertIn("ERROR", stderr)
        self.assertIn(
            "invocation of the 'npm' binary failed;", stderr)
        self.assertIn("terminating due to unexpected exception", stderr)
        self.assertIn("Traceback ", stderr)
        self.assertIn("(Pdb)", sys.stdout.getvalue())

        stub_stdouts(self)
        self.assertNotIn("(Pdb)", stderr)
        rt(['foo', '--install', 'example.package2', '--debugger'])
        self.assertIn("(Pdb)", sys.stdout.getvalue())

    def test_critical_log_exception(self):
        remember_cwd(self)
        tmpdir = mkdtemp(self)
        os.chdir(tmpdir)
        rt = self.setup_runtime()

        stub_stdouts(self)
        # ensure the binary is not found.
        stub_mod_call(self, cli, fake_error(RuntimeError('fake error')))
        rt(['foo', '--install', 'example.package2'])
        self.assertIn(
            "CRITICAL calmjs.runtime RuntimeError: fake error",
            sys.stderr.getvalue())


class MainIntegrationTestCase(unittest.TestCase):
    """
    For testing the main method
    """

    def test_calmjs_main_console_entry_point(self):
        stub_stdouts(self)
        with self.assertRaises(SystemExit) as e:
            runtime.main([])
        self.assertIn('usage', sys.stdout.getvalue())
        self.assertEqual(e.exception.args[0], 0)

    def test_calmjs_main_console_entry_point_help(self):
        stub_stdouts(self)
        with self.assertRaises(SystemExit) as e:
            runtime.main(['-h'])
        self.assertIn('npm', sys.stdout.getvalue())
        self.assertEqual(e.exception.args[0], 0)

    def test_calmjs_main_console_version(self):
        stub_stdouts(self)
        with self.assertRaises(SystemExit) as e:
            runtime.main(['-V'])
        self.assertEqual(e.exception.args[0], 0)
        self.assertIn('calmjs', sys.stdout.getvalue())

    def test_calmjs_main_console_version_broken(self):
        stub_stdouts(self)
        working_set = pkg_resources.WorkingSet([mkdtemp(self)])
        stub_item_attr_value(self, runtime, 'default_working_set', working_set)
        stub_item_attr_value(
            self, calmjs_argparse, 'default_working_set', working_set)
        # make sure the bad case doesn't just blow up...
        with self.assertRaises(SystemExit) as e:
            runtime.main(['-V'])
        self.assertEqual(e.exception.args[0], 0)
        self.assertIn('? ? from ?', sys.stdout.getvalue())

    def test_calmjs_main_runtime_console_version(self):
        stub_stdouts(self)
        with self.assertRaises(SystemExit) as e:
            runtime.main(['npm', '-V'])
        self.assertEqual(e.exception.args[0], 0)
        # reports both versions.
        value = sys.stdout.getvalue()
        self.assertEqual(2, len(value.strip().splitlines()))

    def test_calmjs_main_console_entry_point_install(self):
        remember_cwd(self)
        tmpdir = mkdtemp(self)
        os.chdir(tmpdir)
        stub_stdouts(self)
        stub_mod_call(self, cli, fake_error(IOError))

        with self.assertRaises(SystemExit) as e:
            runtime.main(['npm', '--init', 'calmjs'])
        # this should be fine, exit code 0
        self.assertEqual(e.exception.args[0], 0)

        with self.assertRaises(SystemExit) as e:
            runtime.main(['npm', '--install', 'calmjs'])
        self.assertIn(
            "invocation of the 'npm' binary failed;", sys.stderr.getvalue())
        self.assertEqual(e.exception.args[0], 1)
