import httplib, os, threading, time, urllib, urlparse
import xbmc, xbmcaddon, xbmcgui, xbmcplugin
from pithos import *



_settings = xbmcaddon.Addon()
_plugin   = _settings.getAddonInfo('id')
_name     = _settings.getAddonInfo('name')
_path     = xbmc.translatePath(_settings.getAddonInfo("profile")).decode("utf-8")
_m4a      = xbmc.translatePath(_settings.getSetting('m4a')).decode("utf-8")

_base     = sys.argv[0]
_handle   = int(sys.argv[1])
_query    = urlparse.parse_qs(sys.argv[2][1:])
_station  = _query.get('station', None)

_playlist = xbmc.PlayList(xbmc.PLAYLIST_MUSIC)
_player   = xbmc.Player()
_pandora  = Pandora()
_stamp    = str(time.time())
_track    = 1
_pend     = 0
_play     = False
_frsh     = False



def panAuth():
    one  = _settings.getSetting('pandoraone')
    name = _settings.getSetting('username')
    word = _settings.getSetting('password')

    try:
        _pandora.connect(one, name, word)
    except PandoraError, e:
        return 0;
    return 1


def panDirectory():
    while not panAuth():
        if xbmcgui.Dialog().yesno(_name, 'Login Failed', '', 'Check username/password and try again?'):
            _settings.openSettings()
        else:
            exit()

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


def panSave(song, path):
    if _settings.getSetting('save') != 'true': return
    xbmc.log("%s.Save (%s) '%s - %s'" % (_plugin, song.songId, song.artist, song.title))
    
    lib = xbmc.translatePath(_settings.getSetting('lib'))
    temp = "%s/%s.strm" % (_m4a, song.songId)
    strm = "%s/%s/%s - %s/%s - %s.strm" % (lib, song.artist, song.artist, song.album, song.artist, song.title)

    file = open(temp, 'w', 0)
    file.write(path)
    file.close()
    os.renames(temp, strm)


def panAdd(song, path):
    global _track, _play, _frsh
    xbmc.log("%s.Add (%s) '%s - %s'" % (_plugin, song.songId, song.artist, song.title))

    li = xbmcgui.ListItem(_station.name)
    li.setProperty(_plugin, _stamp)
    li.setProperty('mimetype', 'audio/aac')
    li.setProperty('Cover', song.artUrl)
    li.setIconImage(song.artUrl)
    li.setThumbnailImage(song.artUrl)

    info = { 'artist' : song.artist, 'album' : song.album, 'title' : song.title, 'rating' : song.rating, 'tracknumber' : _track}
    li.setInfo('music', info)

    _playlist.add(path, li)
    _track += 1
    _play = True
    _frsh = True


def panFetch(song):
    global _pend
    _pend += 1

    path = "%s/%s.m4a" % (_m4a, song.songId)
    if os.path.isfile(path):
        xbmc.log("%s.Fetch DUP (%s) '%s - %s'" % (_plugin, song.songId, song.artist, song.title))
        panAdd(song, path)
        _pend -= 1
        return

    totl = 0
    add  = False
    qual = _settings.getSetting('quality')
    skip = _settings.getSetting('skip');
    isad = int(_settings.getSetting('isad')) * 1024
    url  = urlparse.urlsplit(song.audioUrl[qual]['audioUrl'])
    urlp = url.path + '?' + url.query

    conn = httplib.HTTPConnection(url.netloc)
    conn.request('GET', url.path + '?' + url.query)
    strm = conn.getresponse()
    size = int(strm.getheader('content-length'))
    
    if size == 341980:	# empty song cause requesting to fast
        xbmc.log("%s.Fetch EMPTY (%s, %7d) '%s - %s'" % (_plugin, song.songId, size, song.artist, song.title))
        _pend -= 1
        return

    xbmc.log("%s.Fetch %s (%s, %7d) '%s - %s'" % (_plugin, strm.reason, song.songId, size, song.artist, song.title))

    file = open(path, 'wb', 0)
    data = strm.read(8192) 
    while (data) and (totl < size):
        file.write(data)
        totl += len(data)
        if (not add) and ((skip == 'false') or (totl > isad)):
            add = True
            panAdd(song, path)

        if totl >= size: break

        try:
            data = strm.read(8192)
        except:
            xbmc.log("%s.Fetch TIMEOUT (%s, %7d) '%s - %s'" % (_plugin, song.songId, totl, song.artist, song.title))
    
    file.close()
    if totl <= isad:    # looks like an ad
        if skip == 'true':
            xbmc.log("%s.Fetch SKIP (%s) '%s - %s'" % (_plugin, song.songId, song.artist, song.title))
            os.remove(path)
            _pend -= 1
            return
        else:
            song.artist = song.album = song.title = 'Advertisement'        
            path2 = path + '.ad.m4a'
            os.renames(path, path2)
            path = path2
            panAdd(song, path)
    
    _pend -= 1
    panSave(song, path)


def panFill():
    global _station

    if not panAuth():
        xbmc.log("%s.Fill NOAUTH (%s) '%s'" % (_plugin, _station.id, _station.name))
        return
    if type(_station) is not Station: _station = _pandora.get_station_by_id(_station[0])

    try:
        songs = _station.get_playlist()
    except (PandoraTimeout, PandoraNetError): pass
    except (PandoraAuthTokenInvalid, PandoraAPIVersionError, PandoraError) as e:
        xbmcgui.Dialog().ok(_name, e.message, '', e.submsg)
        exit()

    xbmc.log("%s.Fill (%s, %d) '%s'" % (_plugin, _station.id, len(songs), _station.name))

    for song in songs:
        threading.Thread(target = panFetch, args = (song,)).start()


def panPlay():
    _playlist.clear()
    panFill()

    li = xbmcgui.ListItem(_station.name)
    li.setPath('special://home/addons/' + _plugin + '/empty.mp3')
    li.setProperty(_plugin, _stamp)

    xbmc.sleep(5000)
    start = time.time()
    while not _play:
        xbmc.sleep(1000)
        if (time.time() - start) >= 60:
            xbmc.log("%s.Play: Timed out" % (_plugin))
            xbmcplugin.setResolvedUrl(_handle, False, li)
            exit()

    xbmcplugin.setResolvedUrl(_handle, True, li)
    _player.play(_playlist)
    xbmc.executebuiltin('ActivateWindow(10500)')


def panCheck():
    global _frsh

    if (_pend == 0) and ((_playlist.size() - _playlist.getposition()) <= 1):
        panFill()

    while (_playlist.size() > int(_settings.getSetting('listmax'))) and (_playlist.getposition() > 0):
        xbmc.executeJSONRPC('{"jsonrpc":"2.0", "id":1, "method":"Playlist.Remove", "params":{"playlistid":' + str(xbmc.PLAYLIST_MUSIC) + ', "position":0}}')
        _frsh = True

    if _frsh and (xbmcgui.getCurrentWindowId() == 10500):
        _frsh = False
        xbmc.executebuiltin('ActivateWindow(12006)')
        xbmc.executebuiltin('ActivateWindow(10500)')



# main
if _station is not None:
    if not os.path.isdir(_m4a): os.makedirs(_m4a)
    panPlay()
    while _playlist.getposition() >= 0:
        xbmc.sleep(15000)

        song = _playlist[_playlist.getposition()]
        if song.getProperty(_plugin) == _stamp:
            panCheck()
        else:
            exit()

else:
    panDirectory()
