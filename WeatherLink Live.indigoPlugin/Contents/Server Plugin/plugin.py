#! /usr/bin/env python
# -*- coding: utf-8 -*-
####################

import time
import socket
import json
import logging
import requests

kCurDevVersCount = 0        # current version of plugin devices

POLL_INTERVAL = 15 * 60     # 15 minutes

################################################################################
class WeatherLink(object):

    def __init__(self, device, plugin):
        self.logger = logging.getLogger("Plugin.WeatherLink")
        self.device = device
        self.plugin = plugin
        
        self.address = device.pluginProps.get(u'address', "")
        self.http_port = int(device.pluginProps.get(u'port', 80))
        self.udp_port = None
        self.sock = None

        self.logger.debug(u"WeatherLink __init__ address = {}, port = {}".format(self.address, self.http_port))
        
            
    def __del__(self):
        self.sock.close()
        

    def udp_start(self):
        
        url = "http://{}:{}/v1/real_time".format(self.address, self.http_port)
        try:
            response = requests.get(url, timeout=3.0)
        except requests.exceptions.RequestException as err:
            self.logger.error(u"{}: udp_start() RequestException: {}".format(self.device.name, err))
            return

        try:
            data = response.json()
        except Exception as err:
            self.logger.error(u"{}: udp_start() JSON decode error: {}".format(self.device.name, err))
            return
            
        if data['error']:
            if data['error']['code'] == 409:
                self.logger.debug(u"{}: udp_start() aborting, no ISS sensors".format(self.device.name))
            else:
                self.logger.error(u"{}: udp_start() error, code: {}, message: {}".format(self.device.name, data['error']['code'], data['error']['message']))
            return

        self.logger.debug(u"{}: udp_start() success: broadcast_port = {}, duration = {}".format(self.device.name, data['data']['broadcast_port'], data['data']['duration']))

        # set up socket listener
        
        if not self.sock:
            self.udp_port = int(data['data']['broadcast_port'])
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            self.sock.settimeout(0.1)
            self.sock.bind(('', self.udp_port))


    def udp_receive(self):

        if not self.sock:
            self.logger.threaddebug(u"{}: udp_receive error: no socket".format(self.device.name))
            return
            
        try:
            data, addr = self.sock.recvfrom(2048)
        except socket.timeout, e:
            return
        except socket.error, e:
            self.logger.error(u"{}: udp_receive socket error: {}".format(device.name, e))
            return

        try:
            json_data = json.loads(data.decode("utf-8"))        
        except Exception as err:
            self.logger.error(u"{}: udp_receive JSON decode error: {}".format(self.device.name, err))
            return
            
        self.logger.threaddebug(u"{}: udp_receive success: did = {}, ts = {}, {} conditions".format(self.device.name, json_data['did'], json_data['ts'], len(json_data['conditions'])))
        self.logger.threaddebug("{}".format(json_data))

        stateList = [
            { 'key':'did',      'value':  json_data['did']},
            { 'key':'timestamp','value':  json_data['ts']}
        ]
        self.device.updateStatesOnServer(stateList)
                   
        return json_data['conditions']
        

    def http_poll(self):
        
        url = "http://{}:{}/v1/current_conditions".format(self.address, self.http_port)
        try:
            response = requests.get(url, timeout=3.0)
        except requests.exceptions.RequestException as err:
            self.logger.error(u"{}: http_poll RequestException: {}".format(self.device.name, err))
            return

        try:
            json_data = response.json()
        except Exception as err:
            self.logger.error(u"{}: http_poll JSON decode error: {}".format(self.device.name, err))
            return
            
        if json_data['error']:
            self.logger.error(u"{}: http_poll Bad return code: {}".format(self.device.name, json_data['error']))
            return

        self.logger.debug(u"{}: http_poll success: did = {}, ts = {}, {} conditions".format(self.device.name, json_data['data']['did'], json_data['data']['ts'], len(json_data['data']['conditions'])))
        self.logger.threaddebug("{}".format(json_data))

        stateList = [
            { 'key':'status',   'value':  'OK'},
            { 'key':'error',    'value':  'None'},
            { 'key':'did',      'value':  json_data['data']['did']},
            { 'key':'timestamp','value':  json_data['data']['ts']}
        ]
        self.device.updateStatesOnServer(stateList)

        return json_data['data']['conditions']

        
################################################################################
class Plugin(indigo.PluginBase):

    def __init__(self, pluginId, pluginDisplayName, pluginVersion, pluginPrefs):
        indigo.PluginBase.__init__(self, pluginId, pluginDisplayName, pluginVersion, pluginPrefs)

        pfmt = logging.Formatter('%(asctime)s.%(msecs)03d\t[%(levelname)8s] %(name)20s.%(funcName)-25s%(msg)s', datefmt='%Y-%m-%d %H:%M:%S')
        self.plugin_file_handler.setFormatter(pfmt)

        try:
            self.logLevel = int(self.pluginPrefs[u"logLevel"])
        except:
            self.logLevel = logging.INFO
        self.indigo_log_handler.setLevel(self.logLevel)

    def startup(self):
        self.logger.info(u"Starting WeatherLink Live")

        self.updateNeeded = False
        self.weatherlinks = {}
        self.sensorDevices = {}

        self.next_poll = time.time()

        self.knownDevices = self.pluginPrefs.get(u"knownDevices", indigo.Dict())        
        
        indigo.devices.subscribeToChanges()
    
    def shutdown(self):
        self.logger.info(u"Shutting down WeatherLink Live")

        indigo.activePlugin.pluginPrefs[u"knownDevices"] = self.knownDevices


    def runConcurrentThread(self):

        try:
            while True:

                for link in self.weatherlinks.values():
                    self.processConditions(link.udp_receive())

                if (time.time() > self.next_poll) or self.updateNeeded:
                    self.updateNeeded = False
                    self.next_poll = time.time() + POLL_INTERVAL
                    
                    for link in self.weatherlinks.values():
                        self.processConditions(link.http_poll())
                        self.sleep(1.0)     # two requests too close together causes errors 
                        link.udp_start()
            
                self.sleep(1.0)

        except self.stopThread:
            pass        

################################################################################
#
#   Process the condition data returned from the WLL
#
################################################################################
 
    def processConditions(self, conditions):
    
        if conditions == None:
            return
        
        for sensor in conditions:

            sensor_lsid = str(sensor['lsid'])
            sensor_type = str(sensor['data_structure_type'])
            key = "lsid-" + sensor_lsid
         
            if key in self.sensorDevices:

                sensorStateList = self.sensorDictToList(sensor)
                sensorDev = self.sensorDevices[key]
                sensorDev.updateStatesOnServer(sensorStateList)
                self.logger.threaddebug(u"{}: Updating sensor: {}".format(sensorDev.name, sensorStateList))

            elif key not in self.knownDevices:
                sensorInfo = {"lsid": sensor_lsid, "type": sensor_type, "status": "Available"}
                self.logger.debug(u"Adding sensor {} to knownDevices: {}".format(key, sensorInfo))
                self.knownDevices[key] = sensorInfo


################################################################################
#
#   convert the raw dict the WLL provides to a device-state list, including
#   special handling of UI states
#
################################################################################
              
    def sensorDictToList(self, sensor_dict):
    
        sensorList = []
        for key, value in sensor_dict.items():
            if key in ['temp','temp_in', 'dew_point', 'dew_point_in', 'heat_index_in', 'wind_chill', 'thw_index', 'thsw_index']:
                sensorList.append({'key': key, 'value': value, 'decimalPlaces': 1, 'uiValue': u'{:.1f} °F'.format(value)})
                
            elif key in ['temp_1','temp_2', 'temp_3', 'temp_4']:
                sensorList.append({'key': key, 'value': value, 'decimalPlaces': 1, 'uiValue': u'{:.1f} °F'.format(value)})
                
            elif key in ['hum', 'hum_in']:
                sensorList.append({'key': key, 'value': value, 'decimalPlaces': 0, 'uiValue': u'{:.0f}%'.format(value)})
            
            elif key in ['bar_sea_level', 'bar_trend', 'bar_absolute']:
                sensorList.append({'key': key, 'value': value, 'decimalPlaces': 2, 'uiValue': u'{:.2f} inHg'.format(value)})
            
            elif key in ['wind_speed_last', 'wind_speed_avg_last_1_min', 'wind_speed_avg_last_2_min', 'wind_speed_hi_last_2_min', 
                         'wind_speed_avg_last_10_min', 'wind_speed_hi_last_10_min']:
                sensorList.append({'key': key, 'value': value, 'decimalPlaces': 0, 'uiValue': u'{:.0f} mph'.format(value)})
            
            elif key in ['wind_dir_last', 'wind_dir_scalar_avg_last_1_min', 'wind_dir_scalar_avg_last_2_min', 'wind_dir_at_hi_speed_last_2_min', 
                         'wind_dir_scalar_avg_last_10_min', 'wind_dir_at_hi_speed_last_10_min']:
                sensorList.append({'key': key, 'value': value, 'decimalPlaces': 0, 'uiValue': u'{:.0d}°'.format(value)})
            
            else:        
                sensorList.append({'key': key, 'value': value})
        
        return sensorList


    ########################################
    # Plugin Preference Methods
    ########################################

    def validatePrefsConfigUi(self, valuesDict):
        errorDict = indigo.Dict()

        try:
            self.logLevel = int(valuesDict[u"logLevel"])
        except:
            self.logLevel = logging.INFO
        self.indigo_log_handler.setLevel(self.logLevel)

        if len(errorDict) > 0:
            return (False, valuesDict, errorDict)
        return (True, valuesDict)

    def closedPrefsConfigUi(self, valuesDict, userCancelled):
        if not userCancelled:
            try:
                self.logLevel = int(valuesDict[u"logLevel"])
            except:
                self.logLevel = logging.INFO
            self.indigo_log_handler.setLevel(self.logLevel)
            self.logger.debug(u"WeatherLink Live logLevel = " + str(self.logLevel))


    ########################################
    # Device Management Methods
    ########################################

    def didDeviceCommPropertyChange(self, origDev, newDev):
    
        if newDev.deviceTypeId == "weatherlink":
            if origDev.pluginProps.get('address', None) != newDev.pluginProps.get('address', None):
                return True           
            if origDev.pluginProps.get('port', None) != newDev.pluginProps.get('port', None):
                return True           

        return False
      
    def deviceStartComm(self, device):
        self.logger.debug(u"{}: Starting Device".format(device.name))

        instanceVers = int(device.pluginProps.get('devVersCount', 0))
        if instanceVers == kCurDevVersCount:
            self.logger.threaddebug(u"{}: Device is current version: {}".format(device.name ,instanceVers))
        elif instanceVers < kCurDevVersCount:
            newProps = device.pluginProps
            newProps["devVersCount"] = kCurDevVersCount
            device.replacePluginPropsOnServer(newProps)
            self.logger.debug(u"{}: Updated device version: {} -> {}".format(device.name,  instanceVers, kCurDevVersCount))
        else:
            self.logger.warning(u"{}: Invalid device version: {}".format(device.name, instanceVers))
        
        if device.deviceTypeId == "weatherlink":
 
            self.weatherlinks[device.id] = WeatherLink(device, self)
            
        elif device.deviceTypeId in ['issSensor', 'moistureSensor', 'tempHumSensor', 'baroSensor']:

            key = "lsid-" + device.pluginProps['address']
            self.sensorDevices[key] = device
            self.knownDevices.setitem_in_item(key, 'status', "Active")
            self.updateNeeded = True

        else:
            self.logger.warning(u"{}: Invalid device type: {}".format(device.name, device.deviceTypeId))

     
        self.logger.debug(u"{}: deviceStartComm complete, sensorDevices = {}".format(device.name, self.sensorDevices))
            
    
    def deviceStopComm(self, device):
        self.logger.debug(u"{}: Stopping Device".format(device.name))
        if device.deviceTypeId == "weatherlink":
            del self.weatherlinks[device.id]
        else:
            key = "lsid-" + device.pluginProps['address']
            try:
                del self.sensorDevices[key]
            except:
                pass

        self.logger.threaddebug(u"{}: deviceStopComm complete, sensorDevices = {}".format(device.name, self.sensorDevices))
            
    ################################################################################
    #
    # delegate methods for indigo.devices.subscribeToChanges()
    #
    ################################################################################

    def deviceDeleted(self, device):
        indigo.PluginBase.deviceDeleted(self, device)

        try:
            self.knownDevices.setitem_in_item(device.address, 'status', "Available")
            self.logger.debug(u"deviceDeleted: {} ({})".format(device.name, device.id))
        except Exception, e:
            self.logger.error(u"deviceDeleted error, {}: {}".format(device.name, str(e)))


    ################################################################################
    #        
    # return a list of all "Available" devices (not associated with an Indigo device)
    #
    ################################################################################
    
    def availableDeviceList(self, filter="", valuesDict=None, typeId="", targetId=0):

        sensorTypes = {
            '1': 'ISS Current Conditions Sensor',
            '2': 'Leaf/Soil Moisture Conditions Sensor',
            '3': 'LSS Barometric Conditions Sensor',
            '4': 'LSS Temp/Hum Conditions Sensor'
        }

        self.logger.debug(u"availableDeviceList: filter = {}".format(filter))
        retList =[]
        for devInfo in sorted(self.knownDevices.values()):
            if devInfo['status'] == 'Available' and devInfo['type'] == filter:
                retList.append((devInfo['lsid'], "{}: {}".format(devInfo['lsid'], sensorTypes[filter])))
               
        retList.sort(key=lambda tup: tup[1])
        self.logger.debug(u"availableDeviceList: retList = {}".format(retList))
        return retList


    ########################################
    # Menu Methods
    ########################################

    # doesn't do anything, just needed to force other menus to dynamically refresh
    def menuChanged(self, valuesDict, typeId, devId):
        return valuesDict

    def pollWeatherLinkMenu(self, valuesDict, typeId):
        try:
            deviceId = int(valuesDict["targetDevice"])
        except:
            self.logger.error(u"Bad Device specified for Clear SMTP Queue operation")
            return False

        for linkID, link in self.weatherlinks.items():
            if linkID == deviceId:
                self.processConditions(link.http_poll())            
        return True
 
 
    def dumpKnownDevices(self):
        self.logger.info(u"Known device list:\n" + str(self.knownDevices))
        
    def purgeKnownDevices(self):
        self.logger.info(u"Purging Known device list...")
        for address, data in self.knownDevices.iteritems():
            if data['status'] == 'Available':
                self.logger.info(u"\t{}".format(address))       
                del self.knownDevices[address]


    def pickWeatherLink(self, filter=None, valuesDict=None, typeId=0):
        retList = []
        for link in self.weatherlinks.values():
            retList.append((link.device.id, link.device.name))
        retList.sort(key=lambda tup: tup[1])
        return retList
