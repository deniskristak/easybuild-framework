# Copyright 2020-2020 Ghent University
#
# This file is part of EasyBuild,
# originally created by the HPC team of Ghent University (http://ugent.be/hpc/en),
# with support of Ghent University (http://ugent.be/hpc),
# the Flemish Supercomputer Centre (VSC) (https://www.vscentrum.be),
# Flemish Research Foundation (FWO) (http://www.fwo.be/en)
# and the Department of Economy, Science and Innovation (EWI) (http://www.ewi-vlaanderen.be/en).
#
# https://github.com/easybuilders/easybuild
#
# EasyBuild is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation v2.
#
# EasyBuild is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with EasyBuild.  If not, see <http://www.gnu.org/licenses/>.
#
"""
Support for easybuild-ing from multiple easyconfigs based on
information obtained from provided file (easystack) with build specifications.

:author: Denis Kristak (Inuits)
:author: Pavel Grochal (Inuits)
"""

from easybuild.base import fancylogger
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.filetools import read_file
from easybuild.tools.module_naming_scheme.utilities import det_full_ec_version
from easybuild.tools.utilities import only_if_module_is_available
try:
    import yaml
except ImportError:
    pass
_log = fancylogger.getLogger('easystack', fname=False)


class EasyStack(object):
    """One class instance per easystack. General options + list of all SoftwareSpecs instances"""

    def __init__(self):
        self.software_list = []

    def compose_ec_filenames(self):
        """Returns a list of all easyconfig names"""
        ec_filenames = []
        for sw in self.software_list:
            full_ec_version = det_full_ec_version({
                'toolchain': {'name': sw.toolchain_name, 'version': sw.toolchain_version},
                'version': sw.version,
                'versionsuffix': sw.versionsuffix or '',
            })
            ec_filename = '%s-%s.eb' % (sw.name, full_ec_version)
            ec_filenames.append(ec_filename)
        return ec_filenames

    def print_full_commands(self):
        """Creates easybuild string to be run via terminal."""
        for sw in self.software_list:
            full_ec_version = det_full_ec_version({
                'toolchain': {'name': sw.toolchain_name, 'version': sw.toolchain_version},
                'version': sw.version,
                'versionsuffix': sw.versionsuffix or '',
            })
            ec_filename = '%s-%s.eb' % (sw.name, full_ec_version)
            if sw.robot: robot_suffix = '--robot=%s' % sw.robot
            if sw.parallel: parallel_suffix = '--parallel=%s' % sw.parallel
            if sw.easybuild_version: easybuild_version_suffix = '--easybuild_version=%s' % sw.easybuild_version
            if sw.from_pr: from_pr_suffix = '--from_pr=%s' % sw.from_pr

            full_command = '%s %s %s %s %s' % (ec_filename, robot_suffix, parallel_suffix,
                                               easybuild_version_suffix, from_pr_suffix)
            print(full_command + ';\n')

    # if needed (defined by easystack) include_label is not found among agruments from cmdline, sw cant be installed
    def process_include_labels(self, provided_include_labels):
        for sw in self.software_list:
            for easystack_include_labels in sw['include_labels']:
                # if a match IS NOT FOUND, sw must be deleted
                if easystack_include_labels not in provided_include_labels:
                    self.software_list.remove(sw)

    # if any of exclude_labels (written in easystack) is found among agruments from cmdline, sw cant be installed
    def process_exclude_labels(self, provided_exclude_labels):
        for sw in self.software_list:
            for easystack_exclude_labels in sw['exclude_labels']:
                # if a match IS FOUND, sw must be deleted
                if easystack_exclude_labels in provided_exclude_labels:
                    self.software_list.remove(sw)


class SoftwareSpecs(object):
    """Contains information about every software that should be installed"""

    def __init__(self, name, version, versionsuffix, toolchain_version, toolchain_name, easybuild_version,
                robot, parallel, from_pr, include_labels, exclude_labels):
        self.name = name
        self.version = version
        self.toolchain_version = toolchain_version
        self.toolchain_name = toolchain_name
        self.versionsuffix = versionsuffix
        self.easybuild_version = easybuild_version
        self.robot = robot
        self.parallel = parallel
        self.from_pr = from_pr
        self.include_labels = include_labels
        self.exclude_labels = exclude_labels


class EasyStackParser(object):
    """Parser for easystack files (in YAML syntax)."""

    @only_if_module_is_available('yaml', pkgname='PyYAML')
    @staticmethod
    def parse(filepath):
        """Parses YAML file and assigns obtained values to SW config instances as well as general config instance"""
        yaml_txt = read_file(filepath)
        easystack_raw = yaml.safe_load(yaml_txt)
        easystack = EasyStack()

        try:
            software = easystack_raw["software"]
        except KeyError:
            wrong_structure_file = "Not a valid EasyStack YAML file: no 'software' key found"
            raise EasyBuildError(wrong_structure_file)

        # trying to assign easybuild_version/robot/parallel/from_pr on the uppermost level
        # if anything changes at any lower level, these will get overwritten
        # assign general easystack attributes
        easybuild_version = easystack_raw.get('easybuild_version', False)
        robot = easystack_raw.get('robot', False)
        parallel = easystack_raw.get('parallel', False)
        from_pr = easystack_raw.get('from_pr', False)


        # assign software-specific easystack attributes
        for name in software:
            # ensure we have a string value (YAML parser returns type = dict
            # if levels under the current attribute are present)
            name = str(name)

            try:
                toolchains = software[name]['toolchains']
            except KeyError:
                raise EasyBuildError("Toolchains for software '%s' are not defined in %s", name, filepath)

            for toolchain in toolchains:
                toolchain = str(toolchain)
                toolchain_parts = toolchain.split('-', 1)
                if len(toolchain_parts) == 2:
                    toolchain_name, toolchain_version = toolchain_parts
                elif len(toolchain_parts) == 1:
                    toolchain_name, toolchain_version = toolchain, ''
                else:
                    raise EasyBuildError("Incorrect toolchain specification for '%s' in %s, too many parts: %s",
                                         name, filepath, toolchain_parts)

                try:
                    versions = toolchains[toolchain]['versions']
                except TypeError as err:
                    wrong_structure_err = "An error occurred when interpreting "
                    wrong_structure_err += "the data for software %s: %s" % (name, err)
                    raise EasyBuildError(wrong_structure_err)

                # if version string containts asterisk or labels, raise error (asterisks not supported)
                if '*' in str(versions):
                    asterisk_err = "EasyStack specifications of '%s' in %s contain asterisk. "
                    asterisk_err += "Wildcard feature is not supported yet."
                    raise EasyBuildError(asterisk_err, name, filepath)

                # labels can be specified on a toolchain level
                include_labels = toolchains[toolchain].get('include_labels', False)
                exclude_labels = toolchains[toolchain].get('exclude_labels', False)
                
                # yaml versions can be in different formats in yaml file
                # firstly, check if versions in yaml file are read as a dictionary.
                # Example of yaml structure:
                # ========================================================================
                # versions:
                #   2.21:
                #   2.25:
                #       robot: True
                #       include-labels: '225'
                #   2.23:
                #     versionsuffix: '-R-4.0.0'
                #     parallel: 12
                #   2.26:
                #     from_pr: 1234
                # ========================================================================
                if isinstance(versions, dict):
                    for version in versions:
                        if versions[version] is not None:
                            version_spec = versions[version]

                            versionsuffix = version_spec.get('versionsuffix', False)
                            robot = version_spec.get('robot', robot)
                            parallel = version_spec.get('parallel', parallel)
                            from_pr = version_spec.get('from_pr', from_pr)
                            include_labels = version_spec.get('include-labels', include_labels)
                            exclude_labels = version_spec.get('exclude-labels', exclude_labels)
                        else:
                            versionsuffix = False

                        specs = {
                            'name': name,
                            'toolchain_name': toolchain_name,
                            'toolchain_version': toolchain_version,
                            'version': version,
                            'versionsuffix': versionsuffix,
                            'easybuild_version': easybuild_version,
                            'robot': robot,
                            'parallel': parallel,
                            'from_pr': from_pr,
                            'include_labels': include_labels,
                            'exclude_labels': exclude_labels,

                        }
                        sw = SoftwareSpecs(**specs)

                        # append newly created class instance to the list in instance of EasyStack class
                        easystack.software_list.append(sw)
                    continue

                # is format read as a list of versions?
                # ========================================================================
                # versions:
                #   [2.24, 2.51]
                # ========================================================================
                elif isinstance(versions, list):
                    versions_list = versions

                # format = multiple lines without ':' (read as a string)?
                # ========================================================================
                # versions:
                #   2.24
                #   2.51
                # ========================================================================
                elif isinstance(versions, str):
                    versions_list = str(versions).split()

                # format read as float (containing one version only)?
                # ========================================================================
                # versions:
                #   2.24
                # ========================================================================
                elif isinstance(versions, float):
                    versions_list = [str(versions)]

                # if no version is a dictionary, neither 
                # versionsuffix, robot, parallel, easybuild_version nor from_pr,are specified on this level
                versionsuffix = False
                easybuild_version = easybuild_version or False
                robot = robot or False
                parallel = parallel or False
                from_pr = from_pr or False
                include_labels = include_labels or False
                exclude_labels = exclude_labels or False

                if easybuild_version != False or robot != False or parallel != False or from_pr != False:
                    print_only = True

                for version in versions_list:
                    sw = SoftwareSpecs(
                        name=name, version=version, versionsuffix=versionsuffix,
                        toolchain_name=toolchain_name, toolchain_version=toolchain_version,
                        easybuild_version=easybuild_version, robot=robot, parallel=parallel, from_pr=from_pr,
                        include_labels = include_labels, exclude_labels = exclude_labels
                        )
                    # append newly created class instance to the list in instance of EasyStack class
                    easystack.software_list.append(sw)
        return easystack, print_only


def parse_easystack(filepath, include_labels, exclude_labels):
    """Parses through easystack file, returns what EC are to be installed together with their options."""
    log_msg = "Support for easybuild-ing from multiple easyconfigs based on "
    log_msg += "information obtained from provided file (easystack) with build specifications."
    _log.experimental(log_msg)
    _log.info("Building from easystack: '%s'" % filepath)

    # class instance which contains all info about planned build
    easystack, print_only = EasyStackParser.parse(filepath)

    easystack.process_include_labels(include_labels)
    easystack.process_exclude_labels(exclude_labels)

    easyconfig_names = easystack.compose_ec_filenames()

    if print_only:
        easystack.print_full_commands()

    _log.debug("EasyStack parsed. Proceeding to install these Easyconfigs: \n'%s'" % "',\n'".join(easyconfig_names))

    return easyconfig_names, print_only
