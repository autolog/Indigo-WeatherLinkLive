#! /usr/bin/env python
# -*- coding: utf-8 -*-
####################

import time
import socket
import json
import logging
import requests
from aprs import APRS

kCurDevVersCount = 0        # current version of plugin devices

POLL_INTERVAL = (10 * 60.0) + 42.0     # 10 minutes, plus a little to avoid exact hour boundaries

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
    
        if not self.device.pluginProps['enableUDP']:
            self.logger.debug(u"{}: udp_start() aborting, not enabled".format(self.device.name))
            return
        
        url = "http://{}:{}/v1/real_time".format(self.address, self.http_port)
        try:
            response = requests.get(url, timeout=3.0)
        except requests.exceptions.RequestException as err:
            self.logger.error(u"{}: udp_start() RequestException: {}".format(self.device.name, err))
            stateList = [
                { 'key':'status',   'value': 'HTTP Error'},
                { 'key':'error',    'value': err.strerror}
            ]
            self.device.updateStatesOnServer(stateList)
            self.device.updateStateImageOnServer(indigo.kStateImageSel.SensorTripped)
            return

        try:
            json_data = response.json()
        except Exception as err:
            self.logger.error(u"{}: udp_start() JSON decode error: {}".format(self.device.name, err))
            stateList = [
                { 'key':'status',   'value':'JSON Error'},
                { 'key':'error',    'value': err.strerror}
            ]
            self.device.updateStatesOnServer(stateList)
            self.device.updateStateImageOnServer(indigo.kStateImageSel.SensorTripped)
            return
            
        if json_data['error']:
            if json_data['error']['code'] == 409:
                self.logger.debug(u"{}: udp_start() aborting, no ISS sensors".format(self.device.name))
            else:
                self.logger.error(u"{}: udp_start() error, code: {}, message: {}".format(self.device.name, json_data['error']['code'], json_data['error']['message']))
            stateList = [
                { 'key':'status',   'value': 'Server Error'},
                { 'key':'error',    'value': json_data['error']}
            ]
            self.device.updateStatesOnServer(stateList)
            self.device.updateStateImageOnServer(indigo.kStateImageSel.SensorTripped)
            return

        self.logger.debug(u"{}: udp_start() broadcast_port = {}, duration = {}".format(self.device.name, json_data['data']['broadcast_port'], json_data['data']['duration']))

        # set up socket listener
        
        if not self.sock:
            try:
                self.udp_port = int(json_data['data']['broadcast_port'])
                self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
                self.sock.settimeout(0.1)
                self.sock.bind(('', self.udp_port))
            except:
                self.logger.error(u"{}: udp_start() RequestException: {}".format(self.device.name, err))
                stateList = [
                    { 'key':'status',   'value': 'Socket Error'},
                    { 'key':'error',    'value': err.strerror }
                ]
                self.device.updateStatesOnServer(stateList)
            else:
                self.logger.debug(u"{}: udp_start() socket listener started".format(self.device.name))


    def udp_receive(self):

        if not self.sock:
            self.logger.threaddebug(u"{}: udp_receive error: no socket".format(self.device.name))
            return
            
        try:
            data, addr = self.sock.recvfrom(2048)
        except socket.timeout, err:
            return
        except socket.error, err:
            self.logger.error(u"{}: udp_receive socket error: {}".format(device.name, err))
            stateList = [
                { 'key':'status',   'value':'socket Error'},
                { 'key':'error',    'value': err.strerror}
            ]
            self.device.updateStatesOnServer(stateList)
            self.device.updateStateImageOnServer(indigo.kStateImageSel.SensorTripped)
            return

        try:
            raw_data = data.decode("utf-8")
            self.logger.threaddebug("{}".format(raw_data))
            json_data = json.loads(raw_data)        
        except Exception as err:
            self.logger.error(u"{}: udp_receive JSON decode error: {}".format(self.device.name, err))
            stateList = [
                { 'key':'status',   'value':'JSON Error'},
                { 'key':'error',    'value': err.strerror}
            ]
            self.device.updateStatesOnServer(stateList)
            self.device.updateStateImageOnServer(indigo.kStateImageSel.SensorTripped)
            return
            
        self.logger.threaddebug(u"{}: udp_receive success: did = {}, ts = {}, {} conditions".format(self.device.name, json_data['did'], json_data['ts'], len(json_data['conditions'])))
        self.logger.threaddebug("{}".format(json_data))

        time_string = time.strftime("%a, %d %b %Y %H:%M:%S", time.localtime(float(json_data['ts'])))

        stateList = [
            { 'key':'did',      'value':  json_data['did']},
            { 'key':'timestamp','value':  time_string}
        ]
        self.device.updateStatesOnServer(stateList)
                   
        return json_data['conditions']
        

    def http_poll(self):
        
        url = "http://{}:{}/v1/current_conditions".format(self.address, self.http_port)
        try:
            response = requests.get(url, timeout=3.0)
        except requests.exceptions.RequestException as err:
            self.logger.error(u"{}: http_poll RequestException: {}".format(self.device.name, err))
            stateList = [
                { 'key':'status',   'value': 'HTTP Error'},
                { 'key':'error',    'value': err.strerror}
            ]
            self.device.updateStatesOnServer(stateList)
            self.device.updateStateImageOnServer(indigo.kStateImageSel.SensorTripped)
            return

        try:
            json_data = response.json()
        except Exception as err:
            self.logger.error(u"{}: http_poll JSON decode error: {}".format(self.device.name, err))
            stateList = [
                { 'key':'status',   'value': 'JSON Error'},
                { 'key':'error',    'value': err.strerror}
            ]
            self.device.updateStatesOnServer(stateList)
            self.device.updateStateImageOnServer(indigo.kStateImageSel.SensorTripped)
            return

        self.logger.threaddebug("{}".format(response.text))
            
        if json_data['error']:
            self.logger.error(u"{}: http_poll Bad return code: {}".format(self.device.name, json_data['error']))
            stateList = [
                { 'key':'status',   'value': 'Server Error'},
                { 'key':'error',    'value': json_data['error']}
            ]
            self.device.updateStatesOnServer(stateList)
            self.device.updateStateImageOnServer(indigo.kStateImageSel.SensorTripped)
            return

        self.logger.debug(u"{}: http_poll success: did = {}, ts = {}, {} conditions".format(self.device.name, json_data['data']['did'], json_data['data']['ts'], len(json_data['data']['conditions'])))
        self.logger.threaddebug("{}".format(json_data))

        time_string = time.strftime("%a, %d %b %Y %H:%M:%S", time.localtime(float(json_data['data']['ts'])))

        stateList = [
            { 'key':'status',   'value':  'OK'},
            { 'key':'error',    'value':  'None'},
            { 'key':'did',      'value':  json_data['data']['did']},
            { 'key':'timestamp','value':  time_string}
        ]
        self.device.updateStatesOnServer(stateList)
        self.device.updateStateImageOnServer(indigo.kStateImageSel.SensorOn)

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
        self.weatherlinks = {}          # Dict of Indigo WeatherLink devices, indexed by device.id
        self.sensorDevices = {}         # Dict of Indigo sensor/transmitter devices, indexed by device.id
        self.aprs_senders = {}          # Dict of Indigo APRS account devices, indexed by device.id
        self.knownDevices = {}          # Dict of sensor/transmitter devices received by base station, indexed by lsid
        
        self.next_poll = time.time()
        self.next_aprs_update = time.time() + 10
                    
    def shutdown(self):
        self.logger.info(u"Shutting down WeatherLink Live")


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
                        self.sleep(1.0)     # requests too close together causes errors 
                        link.udp_start()

                if time.time() > self.next_aprs_update:
                    self.next_aprs_update = time.time() + POLL_INTERVAL
                    
                    for aprs in self.aprs_senders.values():
                        aprs.send_update()

            
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
        
        for condition in conditions:

            sensor_lsid = str(condition['lsid'])
            sensor_type = str(condition['data_structure_type'])
         
            if sensor_lsid not in self.knownDevices:
                sensorInfo = {"lsid": sensor_lsid, "type": sensor_type}
                self.knownDevices[sensor_lsid] = sensorInfo
                self.logger.debug(u"Added sensor {} to knownDevices: {}".format(sensor_lsid, sensorInfo))
                continue
                

            for sensorDev in self.sensorDevices.values():
                if sensorDev.address == sensor_lsid:
                    stateList = self.sensorDictToList(condition)
                    sensorDev.updateStatesOnServer(stateList)
                    self.logger.threaddebug(u"{}: Updating sensor: {}".format(sensorDev.name, stateList))


################################################################################
#
#   convert the raw dict the WLL provides to a device-state list, including conversion and UI state generation
#
################################################################################
              
    def sensorDictToList(self, sensor_dict):
    
        # get values to convert rain counts to actual units
        rainCollector = {   0: (None, None),
                            1: (0.01,  "in"),
                            2: (0.2,   "mm"),
                            3: (0.1,   "mm"),
                            4: (0.001, "in")
        }
        factor, units = rainCollector[sensor_dict.get('rain_size', 1)]
        
        sensorList = []
        for key, value in sensor_dict.items():
        
            # consolidate redundant states (same info from http and udp with different names)
            if key == "rainfall_last_15_min":
                key = "rain_15_min"
            elif key == "rainfall_last_60_min":
                key = "rain_60_min"
            elif key == "rainfall_last_24_hr":
                key = "rain_24_hr"

        
            if value == None:
                sensorList.append({'key': key, 'value': ''})
            
            elif key in ['temp','temp_in', 'dew_point', 'dew_point_in', 'heat_index_in', 'wind_chill', 'wet_bulb', 'heat_index', 'thw_index', 'thsw_index']:
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
                sensorList.append({'key': key, 'value': value, 'decimalPlaces': 0, 'uiValue': u'{:d}°'.format(value)})
            
            elif key in ['rain_storm_start_at', 'rain_storm_last', 'rain_storm_last_end_at', 'rain_storm_last_start_at', 'timestamp']:
                time_string = time.strftime("%a, %d %b %Y %H:%M:%S", time.localtime(float(value)))
                sensorList.append({'key': key, 'value': time_string, 'decimalPlaces': 0, 'uiValue': u'{}'.format(time_string)})

            elif key in ['rain_rate_last', 'rain_rate_hi', 'rain_rate_hi_last_15_min']:
                rain = float(value) * factor
                sensorList.append({'key': key, 'value': rain, 'decimalPlaces': 2, 'uiValue': u'{:.2f} {}/hr'.format(rain, units)})
            
            elif key in ['rain_15_min', 'rain_60_min', 'rain_24_hr', 'rain_storm', 'rain_storm_last',
                        'rainfall_daily', 'rainfall_monthly', 'rainfall_year']:
                rain = float(value) * factor
                sensorList.append({'key': key, 'value': rain, 'decimalPlaces': 2, 'uiValue': u'{:.2f} {}'.format(rain, units)})
            
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

        device.stateListOrDisplayStateIdChanged()
                
        if device.deviceTypeId == "weatherlink":
 
            self.weatherlinks[device.id] = WeatherLink(device, self)
            device.updateStateImageOnServer(indigo.kStateImageSel.SensorOn)
            
        elif device.deviceTypeId == "aprs_sender":
 
            self.aprs_senders[device.id] = APRS(device)
            
        elif device.deviceTypeId in ['issSensor', 'moistureSensor', 'tempHumSensor', 'baroSensor']:

            if device.pluginProps.get('status_state', None) in ["temp", "temp_in", "dew_point", "dew_point_in", "heat_index", 
                "heat_index_in", "wind_chill", "temp_1", "temp_2", "temp_3", "temp_4"]:
                device.updateStateImageOnServer(indigo.kStateImageSel.TemperatureSensorOn)

            elif device.pluginProps.get('status_state', None) in ["rain_15_min", "rain_60_min", "rain_24_hr"]:
                device.updateStateImageOnServer(indigo.kStateImageSel.Auto)

            elif device.pluginProps.get('status_state', None) in ["hum", "hum_in", "moist_soil_1", "moist_soil_2", "moist_soil_3", 
                "moist_soil_4", "wet_leaf_1", "wet_leaf_2"]:
                device.updateStateImageOnServer(indigo.kStateImageSel.HumiditySensorOn)
        			
            elif device.pluginProps.get('status_state', None) in ["bar_sea_level", "bar_absolute"]:
                device.updateStateImageOnServer(indigo.kStateImageSel.Auto)

            elif device.pluginProps.get('status_state', None) in ["wind_speed_last", "wind_speed_avg_last_2_min"]:
                device.updateStateImageOnServer(indigo.kStateImageSel.WindSpeedSensor)

            else:
                device.updateStateImageOnServer(indigo.kStateImageSel.Auto)

            self.sensorDevices[device.id] = device

        else:
            self.logger.warning(u"{}: Invalid device type: {}".format(device.name, device.deviceTypeId))

        self.updateNeeded = True
        self.logger.debug(u"{}: deviceStartComm complete, sensorDevices = {}".format(device.name, self.sensorDevices))

            
    
    def deviceStopComm(self, device):
        self.logger.debug(u"{}: Stopping Device".format(device.name))
        if device.deviceTypeId == "weatherlink":
            del self.weatherlinks[device.id]
        elif device.deviceTypeId == "aprs_sender":
            del self.aprs_senders[device.id]
        else:
            del self.sensorDevices[device.id]

        self.logger.debug(u"{}: deviceStopComm complete, sensorDevices = {}".format(device.name, self.sensorDevices))
            
            
    def getDeviceDisplayStateId(self, device):
            
        try:
            status_state = device.pluginProps['status_state']
        except:
            status_state = indigo.PluginBase.getDeviceDisplayStateId(self, device)
            
        self.logger.debug(u"{}: getDeviceDisplayStateId returning: {}".format(device.name, status_state))

        return status_state
    
    
    ################################################################################
    #        
    # return a list of all "Available" devices (not associated with an Indigo device)
    #
    ################################################################################
    
    def availableDeviceList(self, filter="", valuesDict=None, typeId="", targetId=0):
        self.logger.debug(u"availableDeviceList: filter = {}, targetId = {}".format(filter, targetId))

        sensorTypes = {
            '1': 'Integrated Sensor Suite',
            '2': 'Leaf/Soil Moisture Sensors',
            '3': 'Internal Barometric Sensor',
            '4': 'Internal Temperature/Humidity Sensor'
        }

        retList =[]
        for devInfo in self.knownDevices.values():
            if devInfo['type'] == filter:
                retList.append((devInfo['lsid'], "{}: {}".format(devInfo['lsid'], sensorTypes[filter])))               
        retList.sort(key=lambda tup: tup[1])
        self.logger.debug(u"availableDeviceList: retList = {}".format(retList))
        return retList
        

    def issDeviceList(self, filter=None, valuesDict=None, typeId=0, targetId=0):
        retList = []
        for sensor in self.sensorDevices.values():
            if sensor.deviceTypeId == "issSensor":
                retList.append((sensor.id, sensor.name))
        retList.sort(key=lambda tup: tup[1])
        return retList

    def baroDeviceList(self, filter=None, valuesDict=None, typeId=0, targetId=0):
        retList = []
        for sensor in self.sensorDevices.values():
            if sensor.deviceTypeId == "baroSensor":
                retList.append((sensor.id, sensor.name))
        retList.sort(key=lambda tup: tup[1])
        return retList


    def pickWeatherLink(self, filter=None, valuesDict=None, typeId=0, targetId=0):
        retList = []
        for link in self.weatherlinks.values():
            retList.append((link.device.id, link.device.name))
        retList.sort(key=lambda tup: tup[1])
        return retList


    ########################################
    # Menu Methods
    ########################################

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
        
    # doesn't do anything, just needed to force other menus to dynamically refresh
    def menuChanged(self, valuesDict, typeId, devId):
        return valuesDict


