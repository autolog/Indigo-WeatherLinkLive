# ****************************************************************************************
# Based on Py-weather
# ****************************************************************************************

import indigo

import logging
import time

from datetime import datetime
from socket import socket, AF_INET, SOCK_STREAM

class PWS(object):


    def __init__(self, device):

        self.logger = logging.getLogger("Plugin.PWS")
        self.device = device
        
        self.address     = self.device.pluginProps.get('address', None)
        self.password    = self.device.pluginProps.get('password', None)
        self.server_host = self.device.pluginProps.get('host', 'www.pwsweather.com')
        self.server_port = self.device.pluginProps.get('port', 80)

        self.iss_device =  indigo.devices[int(self.device.pluginProps.get('iss_device', None))]
        self.baro_device = indigo.devices[int(self.device.pluginProps.get('baro_device', None))]

        self.logger.debug(u"{}: PWS station_id = {}, server_host = {}, server_port = {}".format(self.device.name, self.address, self.server_host, self.server_port))

    def send_update(self):

        URI = "/pwsupdate/pwsupdate.php"
        url = "http://{}:{}/{}".format(self.server_host, self.server_port, URI)
        
        data = {
            'ID': self.address,
            'PASSWORD': self.password,
            'action':'updateraw',
            'softwaretype': 'Indigo WeatherLink Live', 
            'dateutc': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        
            'tempf': float(self.iss_device.states['temp']),
            'baromin': float(self.baro_device.states['bar_absolute']),
            'dewptf': float(self.iss_device.states['dew_point']),
            'humidity': float(self.iss_device.states['hum']),
            'rainin': float(self.iss_device.states['rain_rate_last']),
            'dailyrainin': float(self.iss_device.states['rainfall_daily']),
            'monthrainin': float(self.iss_device.states['rainfall_monthly']),
            'yearrainin': float(self.iss_device.states['rainfall_year']),
            'windspeedmph': float(self.iss_device.states['wind_speed_avg_last_10_min']),
            'windgustmph': float(self.iss_device.states['wind_speed_hi_last_10_min']),
            'winddir': float(self.iss_device.states['wind_dir_scalar_avg_last_10_min']),
        }

        
        self.logger.debug(u"{}: PWS upload data = {}".format(data))
            
        try:
            r = requests.get(url, params=data)
            self.logger.debug(u"{}: PWS url = {}".format(self.device.name, r.url))
            self.logger.debug(u"{}: PWS response = {}".format(self.device.name, r.text))
        except Exception as err:
            self.logger.error(u"{}: send_update error: {}".format(self.device.name, err))

