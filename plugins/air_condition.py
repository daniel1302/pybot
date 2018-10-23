import json
import requests
import threading

from datetime import timedelta
from fuzzywuzzy import process, fuzz

from plugin import *


# TODO lock?
# TODO measurement time?
# TODO performance
# TODO too many stations
# TODO search by street name
# TODO check lru_cache
# TODO what if empty, exception safety, corner cases

class air_condition(plugin):
    class station:
        def __init__(self, id, name):
            self.id = id
            self.name = name

    class measurement:
        def __init__(self, what, index_level, value):
            self.what = what
            self.index_level = index_level
            self.value = value

    class condition:
        def __init__(self, station, measurements):
            self.station = station
            self.measurements = measurements

    def __init__(self, bot):
        super().__init__(bot)
        self.stations_by_city = {}  # city_name -> [stations]

    @command
    @doc('air <city>: get air conditions in <city> from gios.gov.pl')
    def air(self, sender_nick, msg, **kwargs):
        self.logger.info(f'{sender_nick} asks for air conditions in {msg}')

        city_name = self.get_city_name(msg)
        if city_name is None:
            self.bot.say_err()
            return

        conditions = [c for c in self.get_air_condition(city_name) if c.measurements]
        for condition in conditions:
            prefix = color.cyan(f'[{condition.station.name}]')
            measurements = []
            for measurement in condition.measurements:
                measurements.append(f'{measurement.what}: {self.colorize_value(measurement.value, measurement.index_level)} µg/m³')

            self.bot.say(f'{prefix} {" :: ".join(measurements)}')

    @utils.timed_lru_cache(expiration=timedelta(minutes=30), typed=True)
    def get_air_condition(self, city_name):
        self.update_known_stations()
        return [self.condition(station, self.get_measurements(station.id)) for station in self.stations_by_city[city_name]]

    @utils.timed_lru_cache(typed=True)
    def get_city_name(self, msg):
        self.update_known_stations()
        result = process.extract(msg, self.stations_by_city.keys(), scorer=fuzz.token_sort_ratio)
        return result[0][0] if result and len(result[0]) > 1 and result[0][1] > 65 else None

    @utils.timed_lru_cache(expiration=timedelta(hours=12))
    def update_known_stations(self):
        response = requests.get(r'http://api.gios.gov.pl/pjp-api/rest/station/findAll', timeout=10).json()
        stations_by_city = {}
        for station in response:
            city = station['city']['name']
            if city not in stations_by_city: stations_by_city[city] = []
            stations_by_city[city].append(self.station(station['id'], station['stationName']))

        self.stations_by_city = stations_by_city
        self.get_city_name.clear_cache()

    def get_measurements(self, station_id):
        result = []

        for sensor_id in self.get_station_sensors(station_id):
            response = requests.get(r'http://api.gios.gov.pl/pjp-api/rest/data/getData/%s' % sensor_id, timeout=10).json()
            index_level = self.get_index_level(station_id, response['key'])
            if not response['values'] or index_level is None: continue
            value = self.get_newest_measurment_value(response['values'])
            result.append(self.measurement(response['key'], index_level, value))

        return result

    def get_index_level(self, station_id, sensor_name):
        response = requests.get(r'http://api.gios.gov.pl/pjp-api/rest/aqindex/getIndex/%s' % station_id, timeout=10).json()
        try:
            sensor_name = sensor_name.casefold().lower().replace('.', '').replace(' ', '')
            return response[f'{sensor_name}IndexLevel']['id']
        except Exception: return None

    def get_newest_measurment_value(self, values):
        return sorted([v for v in values if 'value' in v and v['value'] is not None], key=lambda x: x['date'], reverse=True)[0]['value']

    def get_station_sensors(self, station_id):
        response = requests.get(r'http://api.gios.gov.pl/pjp-api/rest/station/sensors/%s' % station_id, timeout=10).json()
        return [sensor['id'] for sensor in response]

    def colorize_value(self, value, index_level):
        value = f'{value:.1f}'
        if index_level <= 0: return color.light_green(value)
        if index_level == 1: return color.green(value)
        if index_level == 2: return color.yellow(value)
        if index_level == 3: return color.orange(value)
        if index_level >= 4: return color.light_red(value)
