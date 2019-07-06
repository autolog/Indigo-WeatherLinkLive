#! /usr/bin/env python
# -*- coding: utf-8 -*-
####################

import sys
import time
from datetime import datetime
import json
import logging

kCurDevVersCount = 0        # current version of plugin devices

################################################################################
class WeatherLink(object):

    def __init__(self, device, address, port):
        self.logger = logging.getLogger("Plugin.WeatherLink")
        self.device = device
        self.connected = False

        self.logger.debug(u"WeatherLink __init__ address = {}, port = {}".format(self.address, self.port))

        self.address = device.pluginProps.get(u'address', "")
        self.http_port = int(device.pluginProps.get(u'port', 80))
        self.udp_port = None
        self.sock = None
        
        self.pollingFrequency = float(self.pluginPrefs.get('pollingFrequency', "15")) * 60.0
        self.logger.debug(u"pollingFrequency = {}".format(self.pollingFrequency))
        self.next_poll = time.time()

        # set up socket listener

        url = "http://{}:{}/v1/real_time".format(self.address, self.http_port)
        try:
            response = requests.get(url)
        except requests.exceptions.RequestException as err:
            self.logger.error(u"{}: real_time RequestException: {}".format(self.device.name, err))
            return

        try:
            data = response.json()
        except Exception as err:
            self.logger.error(u"{}: real_time JSON decode error: {}".format(self.device.name, err))
            return
            
        if data['error'] not None:
            self.logger.error(u"{}: real_time Bad return code: {}".format(self.device.name, data['error']))
            return

        self.logger.debug(u"{}: real_time success: broadcast_port = {}, duration = {}".format(self.device.name, data['data']['broadcast_port'], data['data']['duration']))

        self.udp_port = int(data['data']['broadcast_port'])
        
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        self.sock.settimeout(0.1)
        self.sock.bind(('', self.udp_port))

        return True
            
    def __del__(self):
        self.logger.debug(u"WeatherLink __del__")
        self.sock.close()
        
    
    def udp_receive(self):

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
            
        self.logger.debug(u"{}: udp_receive success: did = {}, ts = {}, {} conditions".format(self.device.name, json_data['did'], json_data['ts'], len(json_data['conditions'])))

        if json_data["conditions"] == None:
            return

        for sensor in json_data['conditions']:
            
            lsid = sensor['lsid']
            if lsid in self.sensorDevices:
            
                sensorDev = self.sensorDevices[lsid]
                self.logger.debug(u"{}: Updating sensor ({})".format(sensorDev.name, lsid))
                sensorDev.updateStatesOnServer(sensor)


    def http_poll(self):

        url = "http://{}:{}/v1/current_conditions".format(self.address, self.http_port)
        try:
            response = requests.get(url)
        except requests.exceptions.RequestException as err:
            self.logger.error(u"{}: http_poll RequestException: {}".format(self.device.name, err))
            return

        try:
            data = response.json()
        except Exception as err:
            self.logger.error(u"{}: http_poll JSON decode error: {}".format(self.device.name, err))
            return
            
        if data['error'] not None:
            self.logger.error(u"{}: http_poll Bad return code: {}".format(self.device.name, data['error']))
            return

        self.logger.debug(u"{}: http_poll success: did = {}, ts = {}, {} conditions".format(self.device.name, data['did'], data['ts'], len(data['conditions'])))

        for sensor in data['conditions']:
            
            lsid = sensor['lsid']
            if lsid in self.sensorDevices:
            
                sensorDev = self.sensorDevices[lsid]
                self.logger.debug(u"{}: Updating sensor ({})".format(sensorDev.name, lsid))
                sensorDev.updateStatesOnServer(sensor)

            elif lsid not in self.knownDevices:
                self.logger.debug(u"{}: Adding {} to known sensor list".format(self.device.name, lsid))
            
            else:
                self.logger.debug(u"{}: Skipping known sensor {}".format(self.device.name, lsid))
            
        
        self.next_poll = time.time() + self.pollingFrequency
              

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

        self.weatherlinks = {}
        self.sensorDevices = {}
        self.knownDevices = indigo.activePlugin.pluginPrefs.get(u"knownDevices", indigo.Dict())
   
        indigo.devices.subscribeToChanges()
    
        
    def shutdown(self):
        indigo.activePlugin.pluginPrefs[u"knownDevices"] = self.knownDevices
        self.logger.info(u"Shutting down WeatherLink Live")


    def runConcurrentThread(self):

        try:
            while True:

                for link in self.weatherlinks.values():
                    link.udp_receive()
                    if time.time() > link.next_poll:
                        link.http_poll()     
                    
                self.sleep(0.1)

        except self.stopThread:
            pass        
            

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
 
            self.weatherlinks[device.id] = WeatherLink(device)

            # do initial request and set up socket 
            
        elif device.deviceTypeId in ['issSensor', 'moistureSensor', 'tempHumSensor', 'baroSensor']:
            address = device.pluginProps.get(u'address', "")
            self.sensorDevices[address] = device

        else:
            self.logger.warning(u"{}: Invalid device type: {}".format(device.name, device.deviceTypeId))

     
        self.logger.debug(u"{}: deviceStartComm complete, sensorDevices[] =".format(device.name))
        for key, sensor in self.sensorDevices.iteritems():
            self.logger.debug(u"\tkey = {}, sensor.name = {}, sensor.id = {}".format(key, sensor.device.name, sensor.device.id))
            
    
    def deviceStopComm(self, device):
        self.logger.debug(u"{}: Stopping Device".format(device.name))
        if device.deviceTypeId == "weatherlink":
            del self.weatherlinks[device.id]
        else:
            address = device.pluginProps.get(u'address', "")
            try:
                del self.sensorDevices[address]
            except:
                pass
            
    ################################################################################
    #
    # delegate methods for indigo.devices.subscribeToChanges()
    #
    ################################################################################

    def deviceDeleted(self, device):
        indigo.PluginBase.deviceDeleted(self, device)

        if device.address:
            try:
                devices = self.knownDevices[device.address]['devices']
                devices.remove(device.id)
                self.knownDevices.setitem_in_item(device.address, 'devices', devices)
                self.knownDevices.setitem_in_item(device.address, 'status', "Available")
                self.logger.debug(u"deviceDeleted: {} ({})".format(device.name, device.id))
            except Exception, e:
                self.logger.error(u"deviceDeleted error, {}: {}".format(device.name, str(e)))

    ########################################
            
    # return a list of all "Available" devices (not associated with an Indigo device)
    
    def availableDeviceList(self, filter="", valuesDict=None, typeId="", targetId=0):
        retList =[]
        for address, data in sorted(self.knownDevices.iteritems()):
            if data['status'] == 'Available':
                retList.append((address, "{}: {}".format(address, data['description'])))
               
        retList.sort(key=lambda tup: tup[1])
        return retList

    # return a list of all "Active" devices of a specific type

    def activeDeviceList(self, filter="", valuesDict=None, typeId="discoveredDevice", targetId=0):
        retList =[]
        for address, data in sorted(self.knownDevices.iteritems()):
            if data['status'] == 'Active' and (filter in address) :
                retList.append((address, "{}: {}".format(address, data['description'])))
               
        retList.sort(key=lambda tup: tup[1])
        return retList


    ########################################
    # Menu Methods
    ########################################

    # doesn't do anything, just needed to force other menus to dynamically refresh
    def menuChanged(self, valuesDict, typeId, devId):
        return valuesDict

    def dumpKnownDevices(self):
        self.logger.info(u"Known device list:\n" + str(self.knownDevices))
        
    def purgeKnownDevices(self):
        self.logger.info(u"Purging Known device list...")
        for address, data in self.knownDevices.iteritems():
            if data['status'] == 'Available':
                self.logger.info(u"\t{}".format(address))       
                del self.knownDevices[address]

 