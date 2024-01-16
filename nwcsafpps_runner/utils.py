#!/usr/bin/env python
# -*- coding: utf-8 -*-

# Copyright (c) 2018 - 2022 Pytroll Developers

# Author(s):

#   Adam.Dybbroe <Firstname.Lastname at smhi.se>

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

"""Utility functions for NWCSAF/pps runner(s).
"""

import threading
from trollsift.parser import parse  # @UnresolvedImport
from trollsift.parser import globify
# from trollsift import Parser
from posttroll.message import Message  # @UnresolvedImport
from subprocess import Popen, PIPE
import os
import stat
import shlex
from glob import glob
import socket
from datetime import datetime, timedelta
#: Python 2/3 differences
from six.moves.urllib.parse import urlparse

from posttroll.address_receiver import get_local_ips

import logging
LOG = logging.getLogger(__name__)


class NwpPrepareError(Exception):
    pass


class FindTimeControlFileError(Exception):
    pass


PPS_OUT_PATTERN = ("S_NWC_{segment}_{orig_platform_name}_{orbit_number:05d}_" +
                   "{start_time:%Y%m%dT%H%M%S%f}Z_{end_time:%Y%m%dT%H%M%S%f}Z.{extention}")
PPS_OUT_PATTERN_MULTIPLE = ("S_NWC_{segment1}_{segment2}_{orig_platform_name}_{orbit_number:05d}_" +
                            "{start_time:%Y%m%dT%H%M%S%f}Z_{end_time:%Y%m%dT%H%M%S%f}Z.{extention}")
PPS_STAT_PATTERN = ("S_NWC_{segment}_{orig_platform_name}_{orbit_number:05d}_" +
                    "{start_time:%Y%m%dT%H%M%S%f}Z_{end_time:%Y%m%dT%H%M%S%f}Z_statistics.xml")

SUPPORTED_AVHRR_SATELLITES = ['NOAA-15', 'NOAA-18', 'NOAA-19',
                              'Metop-B', 'Metop-A', 'Metop-C']
SUPPORTED_EARS_AVHRR_SATELLITES = ['Metop-B', 'Metop-C']
SUPPORTED_MODIS_SATELLITES = ['EOS-Terra', 'EOS-Aqua']
SUPPORTED_VIIRS_SATELLITES = ['Suomi-NPP', 'NOAA-20', 'NOAA-21', 'NOAA-22', 'NOAA-23']
SUPPORTED_SEVIRI_SATELLITES = ['Meteosat-09', 'Meteosat-10', 'Meteosat-11']
SUPPORTED_METIMAGE_SATELLITES = ['Metop-SG-A1', 'Metop-SG-A2', 'Metop-SG-A3']

SUPPORTED_PPS_SATELLITES = (SUPPORTED_AVHRR_SATELLITES +
                            SUPPORTED_MODIS_SATELLITES +
                            SUPPORTED_SEVIRI_SATELLITES +
                            SUPPORTED_METIMAGE_SATELLITES +
                            SUPPORTED_VIIRS_SATELLITES)

GEOLOC_PREFIX = {'EOS-Aqua': 'MYD03', 'EOS-Terra': 'MOD03'}
DATA1KM_PREFIX = {'EOS-Aqua': 'MYD021km', 'EOS-Terra': 'MOD021km'}

PPS_SENSORS = ['amsu-a', 'amsu-b', 'mhs', 'avhrr/3', 'viirs', 'modis', 'seviri', 'metimage']
REQUIRED_MW_SENSORS = {}
REQUIRED_MW_SENSORS['NOAA-15'] = ['amsu-a', 'amsu-b']
REQUIRED_MW_SENSORS['NOAA-18'] = []
REQUIRED_MW_SENSORS['NOAA-19'] = ['amsu-a', 'mhs']
REQUIRED_MW_SENSORS['Metop-A'] = ['amsu-a', 'mhs']
REQUIRED_MW_SENSORS['Metop-B'] = ['amsu-a', 'mhs']
REQUIRED_MW_SENSORS['Metop-C'] = ['amsu-a', 'mhs']
NOAA_METOP_PPS_SENSORNAMES = ['avhrr/3', 'amsu-a', 'amsu-b', 'mhs']

METOP_NAME_LETTER = {'metop01': 'metopb', 'metop02': 'metopa', 'metop03': 'metopc'}
METOP_NAME = {'metop01': 'Metop-B', 'metop02': 'Metop-A', 'metop03': 'Metop-C'}
METOP_NAME_INV = {'metopb': 'metop01', 'metopa': 'metop02', 'metopc': 'metop03'}

SATELLITE_NAME = {'NOAA-19': 'noaa19', 'NOAA-18': 'noaa18',
                  'NOAA-15': 'noaa15',
                  'Metop-A': 'metop02', 'Metop-B': 'metop01',
                  'Metop-C': 'metop03',
                  'Metop-SG-A1': 'metopsga1',
                  'Metop-SG-A2': 'metopsga2',
                  'Metop-SG-A3': 'metopsga3',
                  'Suomi-NPP': 'npp',
                  'NOAA-20': 'noaa20', 'NOAA-21': 'noaa21', 'NOAA-23': 'noaa23',
                  'EOS-Aqua': 'eos2', 'EOS-Terra': 'eos1',
                  'Meteosat-09': 'meteosat09', 'Meteosat-10': 'meteosat10',
                  'Meteosat-11': 'meteosat11'}
SENSOR_LIST = {}
for sat in SATELLITE_NAME:
    if sat in ['NOAA-15']:
        SENSOR_LIST[sat] = ['avhrr/3', 'amsu-b', 'amsu-a']
    elif sat in ['EOS-Aqua', 'EOS-Terra']:
        SENSOR_LIST[sat] = 'modis'
    elif sat in ['Suomi-NPP', 'NOAA-20', 'NOAA-21']:
        SENSOR_LIST[sat] = 'viirs'
    elif 'Meteosat' in sat:
        SENSOR_LIST[sat] = 'seviri'
    elif 'Metop-SG' in sat:
        SENSOR_LIST[sat] = 'metimage'
    else:
        SENSOR_LIST[sat] = ['avhrr/3', 'mhs', 'amsu-a']


METOP_SENSOR = {'amsu-a': 'amsua', 'avhrr/3': 'avhrr',
                'amsu-b': 'amsub', 'hirs/4': 'hirs'}


def run_command(cmdstr):
    """Run system command."""
    myargs = shlex.split(str(cmdstr))

    LOG.debug("Command: " + str(cmdstr))
    LOG.debug('Command sequence= ' + str(myargs))
    #: TODO: What is this
    try:
        proc = Popen(myargs, shell=False, stderr=PIPE, stdout=PIPE)
    except NwpPrepareError:
        LOG.exception("Failed when preparing NWP data for PPS...")

    out_reader = threading.Thread(
        target=logreader, args=(proc.stdout, LOG.info))
    err_reader = threading.Thread(
        target=logreader, args=(proc.stderr, LOG.info))
    out_reader.start()
    err_reader.start()
    out_reader.join()
    err_reader.join()

    return proc.wait()


def check_uri(uri):
    """Check that the provided *uri* is on the local host and return the
    file path.
    """
    if isinstance(uri, (list, set, tuple)):
        paths = [check_uri(ressource) for ressource in uri]
        return paths
    url = urlparse(uri)
    try:
        if url.hostname:
            url_ip = socket.gethostbyname(url.hostname)

            if url_ip not in get_local_ips():
                try:
                    os.stat(url.path)
                except OSError:
                    raise IOError(
                        "Data file %s unaccessible from this host" % uri)

    except socket.gaierror:
        LOG.warning("Couldn't check file location, running anyway")

    return url.path


class PpsRunError(Exception):
    pass


class SceneId(object):

    def __init__(self, platform_name, orbit_number, starttime, threshold=5):
        self.platform_name = platform_name
        self.orbit_number = orbit_number
        self.starttime = starttime
        self.threshold = threshold

    def __str__(self):

        return (str(self.platform_name) + '_' +
                str(self.orbit_number) + '_' +
                str(self.starttime.strftime('%Y%m%d%H%M')))

    def __hash__(self):
        return hash(str(self.platform_name) + '_' +
                    str(self.orbit_number) + '_' +
                    str(self.starttime.strftime('%Y%m%d%H%M')))

    def __eq__(self, other):

        return (self.platform_name == other.platform_name and
                self.orbit_number == other.orbit_number and
                abs(self.starttime - other.starttime) < timedelta(minutes=self.threshold))


def message_uid(msg):
    """Create a unique id/key-name for the scene."""

    orbit_number = int(msg.data['orbit_number'])
    platform_name = msg.data['platform_name']
    starttime = msg.data['start_time']

    return SceneId(platform_name, orbit_number, starttime)


def get_sceneid(platform_name, orbit_number, starttime):

    if starttime:
        sceneid = (str(platform_name) + '_' +
                   str(orbit_number) + '_' +
                   str(starttime.strftime('%Y%m%d%H%M%S')))
    else:
        sceneid = (str(platform_name) + '_' +
                   str(orbit_number))

    LOG.debug("Scene identifier = " + str(sceneid))
    return sceneid


def ready2run(msg, files4pps, **kwargs):
    """Check whether pps is ready to run or not."""

    LOG.debug("Ready to run...")
    LOG.info("Got message: " + str(msg))

    destination = msg.data.get('destination')

    uris = []

    if msg.type == 'file':
        if destination is None:
            uris = [(msg.data['uri'])]
        else:
            uris = [os.path.join(destination, msg.data['uid'])]
    else:
        LOG.debug(
            "Ignoring this type of message data: type = " + str(msg.type))
        return False

    try:
        level1_files = check_uri(uris)
    except IOError:
        LOG.info('One or more files not present on this host!')
        return False

    try:
        url_ip = socket.gethostbyname(msg.host)
        if url_ip not in get_local_ips():
            LOG.warning("Server %s not the current one: %s", str(url_ip), socket.gethostname())
            return False
    except (AttributeError, socket.gaierror) as err:
        LOG.error("Failed checking host! Hostname = %s", socket.gethostname())
        LOG.exception(err)

    LOG.info("Sat and Sensor: " + str(msg.data['platform_name'])
             + " " + str(msg.data['sensor']))
    if msg.data['sensor'] not in PPS_SENSORS:
        LOG.info("Data from sensor " + str(msg.data['sensor']) +
                 " not needed by PPS " +
                 "Continue...")
        return False

    if msg.data['platform_name'] in SUPPORTED_SEVIRI_SATELLITES:
        if msg.data['sensor'] not in ['seviri', ]:
            LOG.info(
                'Sensor ' + str(msg.data['sensor']) +
                ' not required for MODIS PPS processing...')
            return False
    elif msg.data['platform_name'] in SUPPORTED_MODIS_SATELLITES:
        if msg.data['sensor'] not in ['modis', ]:
            LOG.info(
                'Sensor ' + str(msg.data['sensor']) +
                ' not required for MODIS PPS processing...')
            return False
    elif msg.data['platform_name'] in SUPPORTED_VIIRS_SATELLITES:
        if msg.data['sensor'] not in ['viirs', ]:
            LOG.info(
                'Sensor ' + str(msg.data['sensor']) +
                ' not required for S-NPP/VIIRS PPS processing...')
            return False
    elif msg.data['platform_name'] in SUPPORTED_METIMAGE_SATELLITES:
        if msg.data['sensor'] not in ['metimage', ]:
            LOG.info(
                'Sensor ' + str(msg.data['sensor']) +
                ' not required for METIMAGE PPS processing...')
            return False
    else:
        if msg.data['sensor'] not in NOAA_METOP_PPS_SENSORNAMES:
            LOG.info(
                'Sensor ' + str(msg.data['sensor']) + ' not required...')
            return False
      
    # The orbit number is mandatory!
    orbit_number = int(msg.data['orbit_number'])
    LOG.debug("Orbit number: " + str(orbit_number))

    # sensor = (msg.data['sensor'])
    platform_name = msg.data['platform_name']

    if platform_name not in SATELLITE_NAME:
        LOG.warning("Satellite not supported: " + str(platform_name))
        return False

    starttime = msg.data.get('start_time')

    LOG.debug("level1_files = %s", level1_files)
    for item in level1_files:
        files4pps[sceneid].append(item)

    LOG.debug("files4pps: %s", str(files4pps[sceneid]))
    if len(files4pps[sceneid]) < 1:
        LOG.info("No level1c files!")
        return False


    if msg.data['platform_name'] in SUPPORTED_PPS_SATELLITES:
        LOG.info(
            "This is a PPS supported scene. Start the PPS lvl2 processing!")
        LOG.info("Process the scene (sat, orbit) = " +
                 str(platform_name) + ' ' + str(orbit_number))

        return True


def terminate_process(popen_obj, scene):
    """Terminate a Popen process."""
    if popen_obj.returncode is None:
        popen_obj.kill()
        LOG.info(
            "Process timed out and pre-maturely terminated. Scene: " + str(scene))
    else:
        LOG.info(
            "Process finished before time out - workerScene: " + str(scene))


def create_pps_call_command_sequence(pps_script_name, scene, options):
    """Create the PPS call commnd sequence.

    Applies to NWCSAF/PPS v2014.
    """
    LVL1_NPP_PATH = os.environ.get('LVL1_NPP_PATH',
                                   options.get('LVL1_NPP_PATH', None))
    LVL1_EOS_PATH = os.environ.get('LVL1_EOS_PATH',
                                   options.get('LVL1_EOS_PATH', None))

    if scene['platform_name'] in SUPPORTED_MODIS_SATELLITES:
        cmdstr = "%s %s %s %s %s" % (pps_script_name,
                                     SATELLITE_NAME[
                                         scene['platform_name']],
                                     scene['orbit_number'], scene[
                                         'satday'],
                                     scene['sathour'])
    else:
        cmdstr = "%s %s %s 0 0" % (pps_script_name,
                                   SATELLITE_NAME[
                                       scene['platform_name']],
                                   scene['orbit_number'])

    cmdstr = cmdstr + ' ' + str(options['aapp_level1files_max_minutes_old'])

    if scene['platform_name'] in SUPPORTED_VIIRS_SATELLITES and LVL1_NPP_PATH:
        cmdstr = cmdstr + ' ' + str(LVL1_NPP_PATH)
    elif scene['platform_name'] in SUPPORTED_MODIS_SATELLITES and LVL1_EOS_PATH:
        cmdstr = cmdstr + ' ' + str(LVL1_EOS_PATH)

    return shlex.split(str(cmdstr))


def create_pps_call_command(python_exec, pps_script_name, scene):
    """Create the pps call command.

    Supports PPSv2021.
    """
    cmdstr = ("%s" % python_exec + " %s " % pps_script_name +
              "-af %s" % scene['file4pps'])
    LOG.debug("PPS call command: %s", str(cmdstr))
    return cmdstr



def get_pps_inputfile(platform_name, ppsfiles):
    """From the set of files picked up in the PostTroll messages decide the input
    file used in the PPS call
    """

    if platform_name in SUPPORTED_MODIS_SATELLITES:
        for ppsfile in ppsfiles:
            if os.path.basename(ppsfile).find('021km') > 0:
                return ppsfile
    elif platform_name in SUPPORTED_AVHRR_SATELLITES:
        for ppsfile in ppsfiles:
            if os.path.basename(ppsfile).find('hrpt_') >= 0:
                return ppsfile
    elif platform_name in SUPPORTED_VIIRS_SATELLITES:
        for ppsfile in ppsfiles:
            if os.path.basename(ppsfile).find('SVM01') >= 0:
                return ppsfile
    elif platform_name in SUPPORTED_SEVIRI_SATELLITES:
        for ppsfile in ppsfiles:
            if os.path.basename(ppsfile).find('NWC') >= 0:
                return ppsfile

    return None


def get_xml_outputfiles(path, platform_name, orb, st_time=''):
    """Finds xml outputfiles depending on certain input criteria.

    From the directory path and satellite id and orbit number,
    scan the directory and find all pps xml output files matching that scene and
    return the full filenames.

    The search allow for small deviations in orbit numbers between the actual
    filename and the message.
    """

    xml_output = (os.path.join(path, 'S_NWC') + '*' +
                  str(METOP_NAME_LETTER.get(platform_name, platform_name)) +
                  '_' + '%.5d' % int(orb) + '_%s*.xml' % st_time)
    LOG.info(
        "Match string to do a file globbing on xml output files: " + str(xml_output))
    filelist = glob(xml_output)

    if len(filelist) == 0:
        # Perhaps there is an orbit number mismatch?
        nxmlfiles = 0
        for idx in [1, -1, 2, -2, 3, -3, 4, -4, 5, -5]:
            tmp_orbit = int(orb) + idx
            LOG.debug('Try with an orbitnumber of %d instead', tmp_orbit)
            xml_output = (os.path.join(path, 'S_NWC') + '*' +
                          str(METOP_NAME_LETTER.get(platform_name, platform_name)) +
                          '_' + '%.5d' % int(tmp_orbit) + '_%s*.xml' % st_time)

            filelist = glob(xml_output)
            nxmlfiles = len(filelist)
            if nxmlfiles > 0:
                break

    return filelist


def create_xml_timestat_from_lvl1c(scene, pps_control_path):
    """From lvl1c file create XML file and return a file list."""
    try:
        txt_time_control = create_pps_file_from_lvl1c(scene['file4pps'], pps_control_path, "timectrl", ".txt")
    except KeyError:
        return []
    if os.path.exists(txt_time_control):
        return create_xml_timestat_from_ascii(txt_time_control, pps_control_path)
    else:
        LOG.warning('No XML Time statistics file created!')
        return []


def find_product_statistics_from_lvl1c(scene, pps_control_path):
    """From lvl1c file find product XML files and return a file list."""
    try:
        glob_pattern = create_pps_file_from_lvl1c(scene['file4pps'], pps_control_path, "*", "_statistics.xml")
        return glob(glob_pattern)
    except KeyError:
        return []


def create_pps_file_from_lvl1c(l1c_file_name, pps_control_path, name_tag, file_type):
    """From lvl1c file create name_tag-file of type file_type."""
    from trollsift import parse, compose
    f_pattern = 'S_NWC_{name_tag}_{platform_id}_{orbit_number}_{start_time}Z_{end_time}Z{file_type}'
    l1c_path, l1c_file = os.path.split(l1c_file_name)
    data = parse(f_pattern, l1c_file)
    data["name_tag"] = name_tag
    data["file_type"] = file_type
    return os.path.join(pps_control_path, compose(f_pattern, data))


def create_xml_timestat_from_ascii(infile, pps_control_path):
    """From ascii file(s) with PPS time statistics create XML file(s) and return a file list."""
    try:
        from pps_time_control import PPSTimeControl
    except ImportError:
        LOG.warning("Failed to import the PPSTimeControl from pps")
        return []
    LOG.info("Time control ascii file: " + str(infile))
    LOG.info("Read time control ascii file and generate XML")
    ppstime_con = PPSTimeControl(infile)
    ppstime_con.sum_up_processing_times()
    try:
        ppstime_con.write_xml()
    except Exception as e:  # TypeError as e:
        LOG.warning('Not able to write time control xml file')
        LOG.warning(e)

    # There should always be only one xml file for each ascii file found above!
    return [infile.replace('.txt', '.xml')]


def publish_pps_files(input_msg, publish_q, scene, result_files, **kwargs):
    """
    Publish messages for the files provided.
    """

    servername = kwargs.get('servername')
    station = kwargs.get('station', 'unknown')

    for result_file in result_files:
        # Get true start and end time from filenames and adjust the end time in
        # the publish message:
        filename = os.path.basename(result_file)
        LOG.info("file to publish = %s", str(filename))
        try:
            try:
                metadata = parse(PPS_OUT_PATTERN, filename)
            except ValueError:
                metadata = parse(PPS_OUT_PATTERN_MULTIPLE, filename)
                metadata['segment'] = '_'.join([metadata['segment1'],
                                                metadata['segment2']])
                del metadata['segment1'], metadata['segment2']
        except ValueError:
            metadata = parse(PPS_STAT_PATTERN, filename)

        endtime = metadata['end_time']
        starttime = metadata['start_time']

        to_send = input_msg.data.copy()
        to_send.pop('dataset', None)
        to_send.pop('collection', None)
        to_send['uri'] = result_file
        to_send['uid'] = filename
        to_send['sensor'] = scene.get('instrument', None)
        if not to_send['sensor']:
            to_send['sensor'] = scene.get('sensor', None)

        to_send['platform_name'] = scene['platform_name']
        to_send['orbit_number'] = scene['orbit_number']
        if result_file.endswith("xml"):
            to_send['format'] = 'PPS-XML'
            to_send['type'] = 'XML'
        if result_file.endswith("nc"):
            to_send['format'] = 'CF'
            to_send['type'] = 'netCDF4'
        to_send['data_processing_level'] = '2'

        to_send['start_time'], to_send['end_time'] = starttime, endtime
        pubmsg = Message('/' + to_send['format'] + '/' +
                         to_send['data_processing_level'] +
                         '/' + station +
                         '/polar/direct_readout/',
                         "file", to_send).encode()
        LOG.info("Sending: %s", str(pubmsg))
        try:
            publish_q.put(pubmsg)
        except Exception:
            LOG.warning("Failed putting message on the queue, will send it now...")
            publish_q.send(pubmsg)


def logreader(stream, log_func):
    while True:
        mystring = stream.readline()
        if not mystring:
            break
        log_func(mystring.strip())
    stream.close()
