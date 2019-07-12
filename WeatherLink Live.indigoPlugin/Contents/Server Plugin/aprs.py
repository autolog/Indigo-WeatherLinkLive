# ****************************************************************************************
# Based on ambient_aprs.py:
# 
# MIT License
# 
# Copyright (c) 2018 Amos Vryhof
# 
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
# 
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
# 
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
# 
# ****************************************************************************************

import indigo

import logging
import time

from datetime import datetime
from socket import socket, AF_INET, SOCK_STREAM

class APRS(object):


    def __init__(self, device):

        self.logger = logging.getLogger("Plugin.APRS")
        self.device = device
        
        self.address     = self.device.pluginProps.get('address', "")
        self.server_host = self.device.pluginProps.get('host', 'cwop.aprs.net')
        self.server_port = self.device.pluginProps.get('port', 14580)

        self.iss_device =  indigo.devices[int(self.device.pluginProps.get('iss_device', None))]
        self.baro_device = indigo.devices[int(self.device.pluginProps.get('baro_device', None))]

        self.logger.debug(u"{}: APRS station_id = {}, server_host = {}, server_port = {}".format(self.device.name, self.address, self.server_host, self.server_port))

        (latitude, longitude) = indigo.server.getLatitudeAndLongitude()
        self.position = "{}/{}".format(self.convert_latitude(latitude), self.convert_longitude(longitude))
        self.logger.debug(u"{}: self.position = {}".format(self.device.name, self.position))


    def decdeg2dmm_m(self, degrees_decimal):
        is_positive = degrees_decimal >= 0
        degrees_decimal = abs(degrees_decimal)
        minutes, seconds = divmod(degrees_decimal * 3600, 60)
        degrees, minutes = divmod(minutes, 60)
        degrees = degrees if is_positive else -degrees

        degrees = str(int(degrees)).zfill(2).replace('-', '0')
        minutes = str(round(minutes + (seconds / 60), 2)).zfill(5)

        return {'degrees': degrees, 'minutes': minutes}


    def convert_latitude(self, degrees_decimal):
        det = self.decdeg2dmm_m(degrees_decimal)
        if degrees_decimal > 0:
            direction = 'N'
        else:
            direction = 'S'

        degrees = det.get('degrees')
        minutes = det.get('minutes')

        lat = '{}{}{}'.format(degrees, str(minutes), direction)

        return lat


    def convert_longitude(self, degrees_decimal):
        det = self.decdeg2dmm_m(degrees_decimal)
        if degrees_decimal > 0:
            direction = 'E'
        else:
            direction = 'W'

        degrees = det.get('degrees')
        minutes = det.get('minutes')

        lon = '{}{}{}'.format(degrees, str(minutes), direction)

        return lon


    def send_update(self):

        wind_dir = int(self.iss_device.states['wind_dir_scalar_avg_last_10_min'])
        wind_speed = int(self.iss_device.states['wind_speed_avg_last_10_min'])
        wind_gust = int(self.iss_device.states['wind_speed_hi_last_10_min'])
        temperature = float(self.iss_device.states['temp'])
        rain_60_min = float(self.iss_device.states['rain_60_min']) * 100.0
        rain_24_hr = float(self.iss_device.states['rain_24_hr']) * 100.0
        rainfall_daily = float(self.iss_device.states['rainfall_daily']) * 100.0
        humidity = int(self.iss_device.states['hum'])
        pressure = (float(self.baro_device.states['bar_absolute'])/ 0.029530) * 10

        wx_data = '{:03d}/{:03d}g{:03d}t{:03.0f}r{:03.0f}p{:03.0f}P{:03.0f}h{:02d}b{:05.0f}'.format(
            wind_dir, wind_speed, wind_gust, temperature, rain_60_min, rain_24_hr, rainfall_daily, humidity, pressure)
        self.logger.debug(u"{}: wx_data = {}".format(self.device.name, wx_data))
    
        utc_s = datetime.now().strftime("%d%H%M")

        packet_data = '{}>APRS,TCPIP*:@{}z{}_{}Indigo WeatherLink Live APRS\r\n'.format(self.address, utc_s, self.position, wx_data)
        
        try:
            # Create socket and connect to server
            sSock = socket(AF_INET, SOCK_STREAM)
            sSock.connect((self.server_host, int(self.server_port)))

            # Log on
            login = 'user {} pass -1 vers Indigo-aprs.py\r\n'.format(self.address)
            sSock.send(login.encode('utf-8'))
            time.sleep(2)

            # Send packet
            sSock.send(packet_data.encode('utf-8'))
            time.sleep(2)

            # Close socket, must be closed to avoid buffer overflow
            sSock.shutdown(0)
            sSock.close()

            self.logger.debug(u"{}: send_update complete".format(self.device.name))

        except Exception as err:
            self.logger.error(u"{}: send_update error: {}".format(self.device.name, err))

