#! /usr/bin/env python
# -*- coding: utf-8 -*-
####################

try:
    import indigo
except ImportError:
    pass

try:
    import requests
except ImportError:
    pass

from datetime import datetime
import time
import socket
import json
import logging

################################################################################
class WeatherLink(object):

    def __init__(self, device):
        self.logger = logging.getLogger("Plugin.WeatherLink")
        self.device = device
        
        self.address = device.pluginProps.get(u'address', "")
        self.http_port = int(device.pluginProps.get(u'port', 80))
        self.udp_port = None
        self.sock = None

        self.pollFrequency = float(self.device.pluginProps.get('pollingFrequency', "10")) * 60.0

        self.pollingRounding = device.pluginProps.get("pollingRounding", False)

        self.calculateNextPollTime(True)  # Calculate next polling time taking polling rounding into account

        self.logger.debug(u"WeatherLink __init__ address = {}, port = {}, pollFrequency = {}".format(self.address, self.http_port, self.pollFrequency))
        
            
    def __del__(self):
        self.sock.close()
        stateList = [
            { 'key':'status',   'value':  "Off"},
            { 'key':'timestamp','value':  datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
        ]
        self.device.updateStatesOnServer(stateList)
        self.device.updateStateImageOnServer(indigo.kStateImageSel.SensorOff)

    def calculateNextPollTime(self, class_init):
        if self.pollingRounding:
            currentTime = time.time()
            previousRoundedTime = currentTime - (currentTime % self.pollFrequency)  # Calculate previous polling time
            self.next_poll = previousRoundedTime + self.pollFrequency  # Calculate next polling time
        else:
            if class_init:  # If class is being initialised, force immediate poll
                self.next_poll = time.time()
            else:
                self.next_poll = time.time() + self.pollFrequency


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
            except socket.error as err:
                self.logger.error(u"{}: udp_start() RequestException: {}".format(self.device.name, err))
                stateList = [
                    { 'key':'status',   'value': 'Socket Error'},
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
            self.logger.error(u"{}: udp_receive socket error: {}".format(self.device.name, err))
            stateList = [
                { 'key':'status',   'value':'socket Error'},
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
        
        self.logger.info(u"{}: Polling WeatherLink Live".format(self.device.name))
        
        self.calculateNextPollTime(False)  # Calculate next polling time taking polling rounding into account

        url = "http://{}:{}/v1/current_conditions".format(self.address, self.http_port)
        try:
            response = requests.get(url, timeout=3.0)
        except requests.exceptions.RequestException as err:
            self.logger.error(u"{}: http_poll RequestException: {}".format(self.device.name, err))
            stateList = [
                { 'key':'status',   'value': 'HTTP Error'},
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
            ]
            self.device.updateStatesOnServer(stateList)
            self.device.updateStateImageOnServer(indigo.kStateImageSel.SensorTripped)
            return

        self.logger.threaddebug("{}".format(response.text))
            
        if json_data['error']:
            self.logger.error(u"{}: http_poll Bad return code: {}".format(self.device.name, json_data['error']))
            stateList = [
                { 'key':'status',   'value': 'Server Error'},
            ]
            self.device.updateStatesOnServer(stateList)
            self.device.updateStateImageOnServer(indigo.kStateImageSel.SensorTripped)
            return

        self.logger.debug(u"{}: http_poll success: did = {}, ts = {}, {} conditions".format(self.device.name, json_data['data']['did'], json_data['data']['ts'], len(json_data['data']['conditions'])))
        self.logger.threaddebug("{}".format(json_data))

        time_string = time.strftime("%a, %d %b %Y %H:%M:%S", time.localtime(float(json_data['data']['ts'])))

        stateList = [
            { 'key':'status',   'value':  'OK'},
            { 'key':'did',      'value':  json_data['data']['did']},
            { 'key':'timestamp','value':  time_string}
        ]
        self.device.updateStatesOnServer(stateList)
        self.device.updateStateImageOnServer(indigo.kStateImageSel.SensorOn)

        return json_data['data']['conditions']

