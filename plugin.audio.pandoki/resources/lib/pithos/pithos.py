# -*- coding: utf-8; tab-width: 4; indent-tabs-mode: nil; -*-
### BEGIN LICENSE
# Copyright (C) 2010 Kevin Mehall <km@kevinmehall.net>
# Copyright (C) 2012 Christopher Eby <kreed@kreed.org>
#This program is free software: you can redistribute it and/or modify it
#under the terms of the GNU General Public License version 3, as published
#by the Free Software Foundation.
#
#This program is distributed in the hope that it will be useful, but
#WITHOUT ANY WARRANTY; without even the implied warranties of
#MERCHANTABILITY, SATISFACTORY QUALITY, or FITNESS FOR A PARTICULAR
#PURPOSE.  See the GNU General Public License for more details.
#
#You should have received a copy of the GNU General Public License along
#with this program.  If not, see <http://www.gnu.org/licenses/>.
### END LICENSE

from blowfish import Blowfish
from xml.dom import minidom
import re
import json
import logging
import time
import urllib
import urllib2


# This is an implementation of the Pandora JSON API using Android partner
# credentials.
# See http://pan-do-ra-api.wikia.com/wiki/Json/5 for API documentation.

HTTP_TIMEOUT = 30
USER_AGENT = 'pithos'
PLAYLIST_VALIDITY_TIME = 60*60*3
NAME_COMPARE_REGEX = re.compile(r'[^A-Za-z0-9]')

API_ERROR_API_VERSION_NOT_SUPPORTED = 11
API_ERROR_COUNTRY_NOT_SUPPORTED = 12
API_ERROR_INSUFFICIENT_CONNECTIVITY = 13
API_ERROR_READ_ONLY_MODE = 1000
API_ERROR_INVALID_AUTH_TOKEN = 1001
API_ERROR_INVALID_LOGIN = 1002
API_ERROR_LISTENER_NOT_AUTHORIZED = 1003
API_ERROR_PARTNER_NOT_AUTHORIZED = 1010
API_ERROR_PLAYLIST_EXCEEDED = 1039

class PithosError(IOError):
    def __init__(self, message, status=None, submsg=None):
        self.status = status
        self.message = message
        self.submsg = submsg

class PithosAuthTokenInvalid(PithosError): pass
class PithosNetError(PithosError): pass
class PithosAPIVersionError(PithosError): pass
class PithosTimeout(PithosNetError): pass

_client = {
    'false' : {
        'deviceModel': 'android-generic',
        'username': 'android',
        'password': 'AC7IBG09A3DTSYM4R41UJWL07VLN8JI7',
        'rpcUrl': '://tuner.pandora.com/services/json/?',
        'encryptKey': '6#26FRL$ZWD',
        'decryptKey': 'R=U!LH$O2B#',
        'version' : '5',
    },
    'true' : {
        'deviceModel': 'D01',
        'username': 'pandora one',
        'password': 'TVCKIBGS9AO9TSYLNNFUML0743LH82D',
        'rpcUrl': '://internal-tuner.pandora.com/services/json/?',
        'encryptKey': '2%3WCL*JU$MP]4',
        'decryptKey': 'U#IO$RZPAB%VX2',
        'version' : '5',
    }
}


def pad(s, l):
    return s + "\0" * (l - len(s))


class Pithos(object):
    def __init__(self):
        self.opener = urllib2.build_opener()
        pass


    def pandora_encrypt(self, s):
        return "".join([self.blowfish_encode.encrypt(pad(s[i:i+8], 8)).encode('hex') for i in xrange(0, len(s), 8)])


    def pandora_decrypt(self, s):
        return "".join([self.blowfish_decode.decrypt(pad(s[i:i+16].decode('hex'), 8)) for i in xrange(0, len(s), 16)]).rstrip('\x08')


    def json_call(self, method, args={}, https=False, blowfish=True):
        url_arg_strings = []
        if self.partnerId:
            url_arg_strings.append('partner_id=%s'%self.partnerId)
        if self.userId:
            url_arg_strings.append('user_id=%s'%self.userId)
        if self.userAuthToken:
            url_arg_strings.append('auth_token=%s'%urllib.quote_plus(self.userAuthToken))
        elif self.partnerAuthToken:
            url_arg_strings.append('auth_token=%s'%urllib.quote_plus(self.partnerAuthToken))

        url_arg_strings.append('method=%s'%method)
        protocol = 'https' if https else 'http'
        url = protocol + self.rpcUrl + '&'.join(url_arg_strings)

        if self.time_offset:
            args['syncTime'] = int(time.time()+self.time_offset)
        if self.userAuthToken:
            args['userAuthToken'] = self.userAuthToken
        elif self.partnerAuthToken:
            args['partnerAuthToken'] = self.partnerAuthToken
        data = json.dumps(args)

        logging.debug(url)
        logging.debug(data)

        if blowfish:
            data = self.pandora_encrypt(data)

        try:
            req = urllib2.Request(url, data, {'User-agent': USER_AGENT, 'Content-type': 'text/plain'})
            response = self.opener.open(req, timeout=HTTP_TIMEOUT)
            text = response.read()
        except urllib2.HTTPError as e:
            logging.error("HTTP error: %s", e)
            raise PithosNetError(str(e))
        except urllib2.URLError as e:
            logging.error("Network error: %s", e)
            if e.reason[0] == 'timed out':
                raise PithosTimeout("Network error", submsg="Timeout")
            else:
                raise PithosNetError("Network error", submsg=e.reason[1])

        logging.debug(text)

        tree = json.loads(text)

        if tree['stat'] == 'fail':
            code = tree['code']
            msg = tree['message']
            logging.error('fault code: ' + str(code) + ' message: ' + msg)

            if code == API_ERROR_INVALID_AUTH_TOKEN:
                raise PithosAuthTokenInvalid(msg)
            elif code == API_ERROR_COUNTRY_NOT_SUPPORTED:
                 raise PithosError("Pandora not available", code,
                    submsg="Pandora is not available outside the United States.")
            elif code == API_ERROR_API_VERSION_NOT_SUPPORTED:
                raise PithosAPIVersionError(msg)
            elif code == API_ERROR_INSUFFICIENT_CONNECTIVITY:
                raise PithosError("Out of sync", code,
                    submsg="Correct your system's clock. If the problem persists, a Pithos update may be required")
            elif code == API_ERROR_READ_ONLY_MODE:
                raise PithosError("Pandora maintenance", code,
                    submsg="Pandora is in read-only mode as it is performing maintenance. Try again later.")
            elif code == API_ERROR_INVALID_LOGIN:
                raise PithosError("Login Error", code, submsg="Invalid username or password")
            elif code == API_ERROR_LISTENER_NOT_AUTHORIZED:
                raise PithosError("Pandora Error", code,
                    submsg="A Pandora One account is required to access this feature. Uncheck 'Pandora One' in Settings.")
            elif code == API_ERROR_PARTNER_NOT_AUTHORIZED:
                raise PithosError("Login Error", code,
                    submsg="Invalid Pandora partner keys. A Pithos update may be required.")
            elif code == API_ERROR_PLAYLIST_EXCEEDED:
                raise PithosError("Playlist Error", code,
                    submsg="You have requested too many playlists. Try again later.")
            else:
                raise PithosError("Pandora returned an error", code, "%s (code %d)"%(msg, code))

        if 'result' in tree:
            return tree['result']


    def set_url_opener(self, opener):
        self.opener = opener


    def connect(self, one, user, password):
        self.partnerId = self.userId = self.partnerAuthToken = None
        self.userAuthToken = self.time_offset = None

        client = _client[one]
        self.rpcUrl = client['rpcUrl']
        self.blowfish_encode = Blowfish(client['encryptKey'])
        self.blowfish_decode = Blowfish(client['decryptKey'])

        partner = self.json_call('auth.partnerLogin', {
            'deviceModel': client['deviceModel'],
            'username': client['username'], # partner username
            'password': client['password'], # partner password
            'version': client['version']
            },https=True, blowfish=False)

        self.partnerId = partner['partnerId']
        self.partnerAuthToken = partner['partnerAuthToken']

        pandora_time = int(self.pandora_decrypt(partner['syncTime'])[4:14])
        self.time_offset = pandora_time - time.time()
        logging.info("Time offset is %s", self.time_offset)

        user = self.json_call('auth.userLogin', {'username': user, 'password': password, 'loginType': 'user'}, https = True)
        self.userId = user['userId']
        self.userAuthToken = user['userAuthToken']


    def get_stations(self, *ignore):
        self.stations = []

        for s in self.json_call('user.getStationList', { 'includeStationArtUrl' : True })['stations']:
            self.stations.append({ 'id' : s['stationId'], 'token' : s['stationToken'], 'name' : s['stationName'], 'art' : s.get('artUrl') })

        return self.stations


    def get_playlist(self, token, quality = 2):
        qual = [ 'lowQuality', 'mediumQuality', 'highQuality' ]
        self.playlist = []

        for s in self.json_call('station.getPlaylist', { 'stationToken': token, 'includeTrackLength' : True }, https = True)['items']:
            if s.get('adToken'): continue

            song = { 'id' : s['songIdentity'], 'token' : s['trackToken'], 'station' : s['stationId'], 'duration' : s.get('trackLength'),
                 'artist' : s['artistName'],   'album' : s['albumName'],    'title' : s['songName'],       'art' : s['albumArtUrl'],
                 'url' : None, 'bitrate' : 64, 'encoding' : None, 'rating' : '3' }

            while quality < 3:
                if s['audioUrlMap'].get(qual[quality]):
                    song['url']      =     s['audioUrlMap'][qual[quality]]['audioUrl']
                    song['encoding'] =     s['audioUrlMap'][qual[quality]]['encoding']
                    song['bitrate']  = int(s['audioUrlMap'][qual[quality]]['bitrate'])
                    break
                quality += 1

            if s['songRating'] == 1: song['rating'] = '5'
            if song['encoding'] == 'aacplus': song['encoding'] = 'm4a'

            self.playlist.append(song)

        return self.playlist


    def add_feedback(self, trackToken, rating_bool):
        feedback = self.json_call('station.addFeedback', {'trackToken': trackToken, 'isPositive': rating_bool})
        return feedback['feedbackId']


    def del_feedback(self, stationToken, feedbackId):
        self.json_call('station.deleteFeedback', {'feedbackId': feedbackId, 'stationToken': stationToken})


    def set_tired(self, trackToken):
        self.json_call('user.sleepSong', {'trackToken': trackToken})


    def search(self, query, songs = True, artists = False):
        results = self.json_call('music.search', {'searchText': query})
        l = []

        if songs:
            for d in results['songs']:
                l += [{ 'score' : d['score'], 'token' : d['musicToken'], 'artist' : d['artistName'], 'title' : d['songName'] }]
        if artists:
            for d in results['artists']:
                l += [{ 'score' : d['score'], 'token' : d['musicToken'], 'artist' : d['artistName'] }]

        return sorted(l, key=lambda i: i['score'], reverse=True)


    def add_seed(self, stationToken, musicToken):
        self.json_call('station.addMusic', { 'stationToken' : stationToken, 'musicToken' : musicToken} )

