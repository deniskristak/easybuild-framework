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
try:
    import yaml
except ImportError:
    pass
_log = fancylogger.getLogger('easystack', fname=False)


class EasyStack(object):
    """One class instance per easystack. General options + list of all SoftwareSpecs instances"""

    def __init__(self):
        self.easybuild_version = None
        self.robot = False
        self.software_list = []

    def compose_ec_filenames(self):
        """Returns a list of all easyconfig names"""
        ec_filenames = []
        for sw in self.software_list:
            full_ec_version = det_full_ec_version({
                'toolchain': {'name': sw.toolchain_name, 'version': sw.toolchain_version},
                'version': sw.version,
                'versionsuffix': sw.versionsuffix,
            })
            ec_filename = '%s-%s.eb' % (sw.name, full_ec_version)
            ec_filenames.append(ec_filename)
        return ec_filenames

    # flags applicable to all sw (i.e. robot)
    def get_general_options(self):
        """Returns general options (flags applicable to all sw (i.e. --robot))"""
        general_options = {}
        # TODO add support for general_options
        # general_options['robot'] = self.robot
        # general_options['easybuild_version'] = self.easybuild_version
        return general_options


class SoftwareSpecs(object):
    """Contains information about every software that should be installed"""

    def __init__(self, name, version, versionsuffix, toolchain_version, toolchain_name):
        self.name = name
        self.version = version
        self.toolchain_version = toolchain_version
        self.toolchain_name = toolchain_name
        self.versionsuffix = versionsuffix


class EasyStackParser(object):
    """Parser for easystack files (in YAML syntax)."""
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

        # assign software-specific easystack attributes
        for name in software:
            # ensure we have a string value (YAML parser returns type = dict
            # if levels under the current attribute are present)
            name = str(name)
            try:
                toolchains = software[name]['toolchains']
            except KeyError:
                raise EasyBuildError("Toolchains for software '%s' are not defined" % name)
            for toolchain in toolchains:
                toolchain = str(toolchain)
                toolchain_parts = toolchain.split('-', 1)
                if len(toolchain_parts) == 2:
                    toolchain_name, toolchain_version = toolchain_parts
                elif len(toolchain_parts) == 1:
                    toolchain_name, toolchain_version = toolchain, ''
                else:
                    raise EasyBuildError("Incorrect toolchain specification, too many parts: %s", toolchain_parts)

                try:
                    # if version string containts asterisk or labels, raise error (asterisks not supported)
                    versions = toolchains[toolchain]['versions']
                except TypeError as err:
                    wrong_structure_err = "An error occurred when interpreting "
                    wrong_structure_err += "the data for software %s: %s" % (name, err)
                    raise EasyBuildError(wrong_structure_err)
                if '*' in str(versions):
                    asterisk_err = "EasyStack specifications of %s contain asterisk. " % (software)
                    asterisk_err += "Wildcard feature is not supported yet."
                    raise EasyBuildError(asterisk_err)

                # yaml versions can be in different formats in yaml file
                # firstly, check if versions in yaml file are read as a dictionary.
                # Example of yaml structure:
                # ========================================================================
                # versions:
                #   2.25:
                #   2.23:
                #     versionsuffix: '-R-4.0.0'
                # ========================================================================
                if isinstance(versions, dict):
                    for version in versions:
                        if versions[version] is not None:
                            version_spec = versions[version]
                            if 'versionsuffix' in version_spec:
                                versionsuffix = str(version_spec['versionsuffix'])
                            else:
                                versionsuffix = ''
                            if 'exclude-labels' in str(version_spec) or 'include-labels' in str(version_spec):
                                lab_err = "EasyStack specifications of '%s' " % name
                                lab_err += "contain labels. Labels aren't supported yet."
                                raise EasyBuildError(lab_err)
                        else:
                            versionsuffix = ''
                        sw = SoftwareSpecs(
                            name=name, version=version, versionsuffix=versionsuffix,
                            toolchain_name=toolchain_name, toolchain_version=toolchain_version)
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

                # if no version is a dictionary, versionsuffix isn't specified
                versionsuffix = ''

                for version in versions_list:
                    sw = SoftwareSpecs(
                        name=name, version=version, versionsuffix=versionsuffix,
                        toolchain_name=toolchain_name, toolchain_version=toolchain_version)
                    # append newly created class instance to the list in instance of EasyStack class
                    easystack.software_list.append(sw)

            # assign general easystack attributes
            easystack.easybuild_version = easystack_raw.get('easybuild_version', None)
            easystack.robot = easystack_raw.get('robot', False)

        return easystack


def parse_easystack(filepath):
    """Parses through easystack file, returns what EC are to be installed together with their options."""
    log_msg = "Support for easybuild-ing from multiple easyconfigs based on "
    log_msg += "information obtained from provided file (easystack) with build specifications."
    _log.experimental(log_msg)
    _log.info("Building from easystack: '%s'" % filepath)

    # class instance which contains all info about planned build
    easystack = EasyStackParser.parse(filepath)

    easyconfig_names = easystack.compose_ec_filenames()

    general_options = easystack.get_general_options()

    _log.debug("EasyStack parsed. Proceeding to install these Easyconfigs: \n'%s'" % "',\n'".join(easyconfig_names))
    if len(general_options) != 0:
        _log.debug("General options for installation are: \n%s" % str(general_options))
    else:
        _log.debug("No general options were specified in easystack")

    return easyconfig_names, general_options