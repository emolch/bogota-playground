import os
op = os.path

import numpy as num

from pyrocko import trace, util, model, pz
from pyrocko.fdsn import station
from pyrocko.guts import Object, Tuple, String, Timestamp, Float

class Channel(Object):
    nslc = Tuple.T(4, String.T())
    tmin = Timestamp.T(optional=True)
    tmax = Timestamp.T(optional=True)
    lat = Float.T()
    lon = Float.T()
    elevation = Float.T()
    depth = Float.T()
    dip = Float.T()
    azimuth = Float.T()
    input_unit = String.T()
    output_unit = String.T()
    response = trace.FrequencyResponse.T()

    def spans(self, *args):
        if len(args) == 0:
            return True
        elif len(args) == 1:
            return ((self.tmin is None or
                     self.tmin <= args[0]) and
                    (self.tmax is None or
                     args[0] <= self.tmax))

        elif len(args) == 2:
            return ((self.tmin is None or
                     args[1] >= self.tmin) and
                    (self.tmax is None or
                     self.tmax >= args[0]))

class EnhancedSacPzError(Exception):
    pass


def read_enhanced_sac_pz(filename):
    zeros, poles, constant, comments = pz.read_sac_zpk(filename=filename, get_comments=True)
    d = {}
    for line in comments:
        toks = line.split(':', 1)
        if len(toks) == 2:
            temp = toks[0].strip('* \t')
            for k in ('network', 'station', 'location', 'channel', 'start', 'end', 
                      'latitude', 'longitude', 'depth', 'elevation', 'dip', 'azimuth',
                      'input unit', 'output unit'):
                if temp.lower().startswith(k):
                    d[k] = toks[1].strip()

    response = trace.PoleZeroResponse(zeros, poles, constant)

    try:
        channel = Channel(
            nslc=(d['network'], d['station'], d['location'], d['channel']),
            tmin=util.str_to_time(d['start'], format='%Y-%m-%dT%H:%M:%S'),
            tmax=util.str_to_time(d['end'], format='%Y-%m-%dT%H:%M:%S'),
            lat=float(d['latitude']),
            lon=float(d['longitude']),
            elevation=float(d['elevation']),
            depth=float(d['depth']),
            dip=float(d['dip']),
            azimuth=float(d['azimuth']),
            input_unit=d['input unit'],
            output_unit=d['output unit'],
            response=response)
    except:
        raise EnhancedSacPzError('cannot get all required information from file %s' % filename)

    return channel

class MetaData:

    def __init__(self):
        self._content = {}

    def add_channel(self, channel):
        nslc = channel.nslc
        if nslc not in self._content:
            self._content[nslc] = []

        self._content[nslc].append(channel)

    def get_pyrocko_response(
            self, nslc, time=None, timespan=None, fake_input_units=None):

        tt = ()
        if time is not None:
            tt = (time,)
        elif timespan is not None:
            tt = timespan

        candidates = [c for c in self._content.get(nslc, []) if c.spans(*tt)]

        if not candidates:
            raise station.NoResponseInformation('%s.%s.%s.%s' % nslc)
        elif len(candidates) > 1:
            raise station.MultipleResponseInformation('%s.%s.%s.%s' % nslc)

        channel = candidates[0]
        if fake_input_units:
            if channel.input_unit != fake_input_units:
                raise station.NoResponseInformation(
                    'cannot convert between units: %s, %s'
                    % (fake_input_units, channel.input_unit))

        return channel.response

    def get_pyrocko_stations(self, time=None, timespan=None,
                             inconsistencies='warn'):
        
        tt = ()
        if time is not None:
            tt = (time,)
        elif timespan is not None:
            tt = timespan

        by_nsl = {}
        for nslc in self._content.keys():
            nsl = nslc[:3]
            for channel in self._content[nslc]:
                if channel.spans(*tt):
                    if nsl not in by_nsl:
                        by_nsl[nsl] = []
                    by_nsl[nsl].append(channel)

        pstations = []
        for nsl, channels in by_nsl.iteritems():
            vals = []
            for channel in channels:
                vals.append((channel.lat, channel.lon, channel.depth, channel.elevation))

            lats, lons, depths, elevations = zip(*vals)
            same = station.same
            inconsistencies = not (same(lats) and same(lons) and same(depths) and same(elevations))

            if inconsistencies == 'raise':
                raise InconsistentChannelLocations(
                    'encountered inconsistencies in channel '
                    'lat/lon/elevation/depth '
                    'for %s.%s.%s: \n%s' % (nsl + (info,)))

            elif inconsistencies == 'warn':
                logger.warn(
                    'cannot create station object for '
                    '%s.%s.%s due to inconsistencies in '
                    'channel lat/lon/elevation/depth\n%s'
                    % (nsl + (info,)))

                continue

            pchannels = []
            for channel in channels:
                pchannels.append(model.Channel(
                    channel.nslc[-1],
                    azimuth=channel.azimuth,
                    dip=channel.dip))

            pstations.append(model.Station(
                *nsl,
                lat=num.mean(lats),
                lon=num.mean(lons),
                elevation=num.mean(elevations),
                depth=num.mean(depths),
                channels=pchannels))
            
        return pstations

    @property
    def nslc_code_list(self):
        return list(self._content.keys())


def load(dirnames):
    if isinstance(dirnames, basestring):
        dirnames = [dirnames]

    m = MetaData()
    for dn in dirnames:
        for fn in os.listdir(dn):
            channel = read_enhanced_sac_pz(op.join(dn, fn))
            m.add_channel(channel)

    return m
