import time, urlparse
import xbmc, xbmcaddon, xbmcgui, xbmcplugin
import pithos.pandora.data
from pithos.pandora.pandora import *



_settings = xbmcaddon.Addon()
_plugin   = _settings.getAddonInfo('id')
_name     = _settings.getAddonInfo('name')

_base     = sys.argv[0]
_handle   = int(sys.argv[1])
_query    = urlparse.parse_qs(sys.argv[2][1:])
_station  = _query.get('station', None)

_playlist = xbmc.PlayList(xbmc.PLAYLIST_MUSIC)
_player   = xbmc.Player()
_pandora  = Pandora()
_track    = 1
_stamp    = str(time.time())



def panAuth():
    name = _settings.getSetting('username')
    word = _settings.getSetting('password')
    qual = ('lowQuality', 'mediumQuality', 'highQuality')[int(_settings.getSetting('quality'))]

    if _settings.getSetting('pandoraone') == 'true':
        clid = pithos.pandora.data.default_one_client_id
    else:
        clid = pithos.pandora.data.default_client_id

    try:
        _pandora.connect(pithos.pandora.data.client_keys[clid], name, word)
        _pandora.set_audio_quality(qual)
    except PandoraError, e:
        return 0;
    return 1


def panLogin():
    while not panAuth():
        if xbmcgui.Dialog().yesno(_name, 'Login Failed', '', 'Check username/password and try again?'):
            _settings.openSettings()
        else:
            exit()


def panDirectory():
    station = _pandora.stations.pop(0)								# Quickmix
    li = xbmcgui.ListItem(station.name, station.id)
    li.setProperty('IsPlayable', 'true')
    xbmcplugin.addDirectoryItem(_handle, _base + '?station=' + station.id, li)

    sort = _settings.getSetting('sort')
    if   sort == '0':	stations = _pandora.stations						# Normal
    elif sort == '2':	stations = _pandora.stations[::-1]					# Reverse
    else:		stations = sorted(_pandora.stations, key=lambda station: station.name)	# A-Z

    for station in stations:
        li = xbmcgui.ListItem(station.name, station.id)
        li.setProperty('IsPlayable', 'true')
        xbmcplugin.addDirectoryItem(_handle, _base + '?station=' + station.id, li)

    xbmcplugin.endOfDirectory(_handle)


def panFill():
    global _track

    try:
        songs = _station.get_playlist()
    except (PandoraTimeout, PandoraNetError): pass
    except (PandoraAuthTokenInvalid, PandoraAPIVersionError, PandoraError) as e:
        xbmcgui.Dialog().ok(_name, e.message, '', e.submsg)
        exit()

    for song in songs:
        li = xbmcgui.ListItem(_station.name)
        li.setPath(song.audioUrl)
        li.setProperty(_plugin, _stamp)
        li.setProperty('mimetype', 'audio/aac')
        li.setProperty('Cover', song.artRadio)
        li.setIconImage(song.artRadio)
        li.setThumbnailImage(song.artRadio)

        info = { 'tracknumber' : _track, 'album' : song.album, 'artist' : song.artist, 'title' : song.title }
        if song.rating is not None:
            info['rating'] = '5'
        li.setInfo('music', info)

        _playlist.add(song.audioUrl, li)
        _track += 1


def panCheck():
    change = False

    if (_playlist.size() - _playlist.getposition()) <= 1:
        panFill()
        change = True

    while (_playlist.size() > int(_settings.getSetting('listmax'))) and (_playlist.getposition() > 0):
        xbmc.executeJSONRPC('{"jsonrpc":"2.0", "id":1, "method":"Playlist.Remove", "params":{"playlistid":' + str(xbmc.PLAYLIST_MUSIC) + ', "position":0}}')
        change = True

    if change and (xbmcgui.getCurrentWindowId() == 10500):
        xbmc.executebuiltin('ActivateWindow(10500)')


def panPlay():
    _playlist.clear()
    panFill()

    li = xbmcgui.ListItem(_station.name)
    li.setPath('special://home/addons/' + _plugin + '/empty.mp3')
    li.setProperty(_plugin, _stamp)
    xbmcplugin.setResolvedUrl(_handle, True, li)

    _player.play(_playlist)
    xbmc.executebuiltin('ActivateWindow(10500)')


panLogin()

if _station is not None:
    _station = _pandora.get_station_by_id(_station[0])

    panPlay()
    while _playlist[_playlist.getposition()].getProperty(_plugin) == _stamp:
        xbmc.sleep(1000)
        panCheck()

else:
    panDirectory()
