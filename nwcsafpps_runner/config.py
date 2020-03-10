#!/usr/bin/env python
# -*- coding: utf-8 -*-
import pdb

# Copyright (c) 2018 Adam.Dybbroe

# Author(s):

#   Adam.Dybbroe <a000680@c20671.ad.smhi.se>

# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""
"""

import os
import socket

MODE = os.getenv("SMHI_MODE")
if MODE is None:
    #: TODO: Remove later /Erik
    import pwd
    if pwd.getpwuid(os.getuid()).pw_name == 'sm_erjoh':
        MODE = "bi"
    else:
        MODE = "offline"

#     CONFIGFILE = "pps2018_config.ini"
CONFIG_PATH = os.environ.get('PPSRUNNER_CONFIG_DIR', './')
CONFIG_FILE = os.environ.get('PPSRUNNER_CONFIG_FILE', 'pps2018_config.yaml')

LVL1_NPP_PATH = os.environ.get('LVL1_NPP_PATH', None)
LVL1_EOS_PATH = os.environ.get('LVL1_EOS_PATH', None)

def get_config(configfile, service=MODE, procenv=''):
    configfile = os.path.join(CONFIG_PATH, configfile)
    if os.path.splitext(configfile)[1] == '.yaml':
        options = get_config_yaml(configfile, service, procenv)
    elif (os.path.splitext(configfile)[1] == '.ini') or \
            (os.path.splitext(configfile)[1] == '.cfg'):
        options = get_config_init_cfg(configfile, service=MODE)
    else:
        print("%s is not a valid extension for the config file" \
              %os.path.splitext(configfile)[1])
        print("Pleas use .yaml, .ini or .cfg")
        options = -1
    return options


def get_config_init_cfg(configfile, service=MODE):
    #: Python 2/3 differences
    import six
    if six.PY2:
        import ConfigParser
    elif six.PY3:
        import configparser as ConfigParser  # @UnresolvedImport

    conf = ConfigParser.ConfigParser()
    conf.read(configfile)

    options = {}
    for option, value in conf.items(service, raw=True):
        options[option] = value

    subscribe_topics = options.get('subscribe_topics').split(',')
    for item in subscribe_topics:
        if len(item) == 0:
            subscribe_topics.remove(item)

    options['subscribe_topics'] = subscribe_topics
    options['number_of_threads'] = int(options.get('number_of_threads', 5))
    options['maximum_pps_processing_time_in_minutes'] = int(options.get('maximum_pps_processing_time_in_minutes', 20))
    options['servername'] = options.get('servername', socket.gethostname())
    options['station'] = options.get('station', 'unknown')

    return options

def get_config_yaml(configfile, service=MODE, procenv=''):
    """Get the configuration from file"""
    import yaml
    try:
        from yaml import UnsafeLoader
    except ImportError:
        from yaml import Loader as UnsafeLoader
    
    with open(configfile, 'r') as fp_:
        config = yaml.load(fp_, Loader=UnsafeLoader)

    options = {}
    for item in config:
        if not isinstance(config[item], dict):
            options[item] = config[item]
        elif item in [service]:
            for key in config[service]:
                if not isinstance(config[service][key], dict):
                    options[key] = config[service][key]
                elif key in [procenv]:
                    for memb in config[service][key]:
                        options[memb] = config[service][key][memb]
    if isinstance(options.get('subscribe_topics'), str):
        subscribe_topics = options.get('subscribe_topics').split(',')
        for item in subscribe_topics:
            if len(item) == 0:
                subscribe_topics.remove(item)
        options['subscribe_topics'] = subscribe_topics
    
    options['number_of_threads'] = int(options.get('number_of_threads', 5))
    options['maximum_pps_processing_time_in_minutes'] = int(options.get('maximum_pps_processing_time_in_minutes', 20))
    options['servername'] = options.get('servername', socket.gethostname())
    options['station'] = options.get('station', 'unknown')
    if options['run_cmask_prob']:
        options['run_cmask_prob'] = 'yes'
    return options

