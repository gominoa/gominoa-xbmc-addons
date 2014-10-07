import httplib, os, shutil, threading, time, urllib, urllib2, urlparse
import xbmc, xbmcaddon, xbmcgui, xbmcplugin
import musicbrainzngs as _brain
from mutagen.mp4 import MP4
from pithos.pithos import *



_settings = xbmcaddon.Addon()
_plugin   = _settings.getAddonInfo('id')
_name     = _settings.getAddonInfo('name')
_version  = _settings.getAddonInfo('version')
_path     = xbmc.translatePath(_settings.getAddonInfo("profile")).decode("utf-8")

_base     = sys.argv[0]
_handle   = int(sys.argv[1])
_query    = urlparse.parse_qs(sys.argv[2][1:])
_station  = _query.get('station', None)
_thumb    = _query.get('thumb', None)

_playlist = xbmc.PlayList(xbmc.PLAYLIST_MUSIC)
_player   = xbmc.Player()
_pandora  = Pandora()
_lock     = threading.Lock()

_stamp    = str(time.time())
_track    = 1
_play     = False



def panProxy():
    if _settings.getSetting('proxy')   == '0':	# Global
        open = urllib2.build_opener()

    elif _settings.getSetting('proxy') == '1':	# None
        hand = urllib2.ProxyHandler({})
        open = urllib2.build_opener(hand)

    elif _settings.getSetting('proxy') == '2':	# Custom
        host = _settings.getSetting('proxy_host')
        port = _settings.getSetting('proxy_port')
        user = _settings.getSetting('proxy_user')
        word = _settings.getSetting('proxy_pass')

        prox = "http://%s:%s@%s:%s" % (user, word, host, port)
        hand = urllib2.ProxyHandler({ 'http' : prox })
        open = urllib2.build_opener(hand)

    _pandora.set_url_opener(open)


def panAuth():
    panProxy()

    one  = _settings.getSetting('pandoraone')
    name = _settings.getSetting('username')
    word = _settings.getSetting('password')

    try: _pandora.connect(one, name, word)
    except PandoraError, e:
        xbmc.log("%s.Auth BAD" % _plugin, xbmc.LOGDEBUG)
        return False;

    xbmc.log("%s.Auth  OK" % _plugin, xbmc.LOGDEBUG)
    return True


def panDir():
    while not panAuth():
        if xbmcgui.Dialog().yesno(_name, '          Login Failed', 'Bad User / Pass / Proxy', '       Check Settings?'):
            _settings.openSettings()
        else: exit()

    sort = _settings.getSetting('sort')
    stations = _pandora.stations
    quickmix = stations.pop(0)							# Quickmix
    if   sort == '0':	stations = stations					# Normal
    elif sort == '2':	stations = stations[::-1]				# Reverse
    else:		stations = sorted(stations, key=lambda s: s.name)	# A-Z
    stations.insert(0, quickmix)						# Quickmix back on top

    for station in stations:
        li = xbmcgui.ListItem(station.name, station.id)
        li.setProperty('IsPlayable', 'true')

        img = _settings.getSetting("img-%s" % station.id)
        li.setIconImage(img)
        li.setThumbnailImage(img)
        li.addContextMenuItems([('Select Thumb', "RunPlugin(plugin://%s/?thumb=%s)" % (_plugin, station.id))])

        xbmcplugin.addDirectoryItem(_handle, "%s?station=%s" % (_base, station.id), li)

    xbmcplugin.endOfDirectory(_handle, cacheToDisc = False)
    xbmc.log("%s.Dir   OK" % _plugin, xbmc.LOGDEBUG)


def panTag(song, path):
    tag = MP4(path)
    dur = str(int(tag.info.length * 1000))
    res = _brain.search_recordings(limit = 1, query = song.title, artist = song.artist, release = song.album, qdur = dur)['recording-list'][0]
    sco = res['ext:score']

    if sco == '100':
        tag['----:com.apple.iTunes:MusicBrainz Track Id'] = res['id']
        tag['\xa9ART'] = song.artist
        tag['\xa9alb'] = song.album
        tag['\xa9nam'] = song.title

        tag.save()
        xbmc.log("%s.Tag   OK (%s,%6s %%) '%s - %s'" % (_plugin, song.songId, sco, song.artist, song.title))
        return True
    else:
        xbmc.log("%s.Tag FAIL (%s,%6s %%) '%s - %s'" % (_plugin, song.songId, sco, song.artist, song.title))
        return False


def panSave(song, path):
    if _settings.getSetting('mode') != '1': return	# not Save to Library

    tmp = "%s.temp" % (path)
    shutil.copyfile(path, tmp)

    if panTag(song, tmp):
        lib = _settings.getSetting('lib')
        dst = xbmc.translatePath(("%s/%s/%s - %s/%s - %s.m4a" % (lib, song.artist, song.artist, song.album, song.artist, song.title))).decode("utf-8")
        alb = xbmc.translatePath(("%s/%s/%s - %s/folder.jpg"  % (lib, song.artist, song.artist, song.album))                         ).decode("utf-8")
        art = xbmc.translatePath(("%s/%s/folder.jpg"          % (lib, song.artist))                                                  ).decode("utf-8")

        os.renames(tmp, dst)
        try:
            if not os.path.isfile(alb): urllib.urlretrieve(song.artUrl, alb)
            if not os.path.isfile(art): urllib.urlretrieve(song.artUrl, art)
        except: pass

    else: os.remove(tmp)

    xbmc.log("%s.Save  OK (%s)          '%s - %s'" % (_plugin, song.songId, song.artist, song.title), xbmc.LOGDEBUG)


def panQueue(song, path):
    global _track, _play
    track = _track
    _track += 1

    li = xbmcgui.ListItem(_station.name)
    li.setProperty(_plugin, _stamp)
    li.setProperty('mimetype', 'audio/aac')
    li.setProperty('Cover', song.artUrl)
    li.setIconImage(song.artUrl)
    li.setThumbnailImage(song.artUrl)

    info = { 'artist' : song.artist, 'album' : song.album, 'title' : song.title, 'rating' : song.rating, 'tracknumber' : track}
    li.setInfo('music', info)

    _play = True
    _lock.acquire()
    _playlist.add(path, li)
    _lock.release()

    xbmc.log("%s.Queue OK (%s)          '%s - %s'" % (_plugin, song.songId, song.artist, song.title)) #, xbmc.LOGDEBUG)


def panFetch(song, path):
    totl = 0
    qued = False

    skip = _settings.getSetting('skip');
    isad = int(_settings.getSetting('isad')) * 1024
    qual = _settings.getSetting('quality')
    url  = urlparse.urlsplit(song.audioUrl[qual]['audioUrl'])

    conn = httplib.HTTPConnection(url.netloc)
    conn.request('GET', "%s?%s" % (url.path, url.query))
    strm = conn.getresponse()
    size = int(strm.getheader('content-length'))

    if size in (341980, 173310): # empty song cause requesting to fast
        xbmc.log("%s.Fetch EMPTY (%s,%8d) '%s - %s'" % (_plugin, song.songId, size, song.artist, song.title), xbmc.LOGDEBUG)
        return

    xbmc.log("%s.Fetch %s (%s,%8d) '%s - %s'" % (_plugin, strm.reason, song.songId, size, song.artist, song.title))

    file = open(path, 'wb', 0)
    data = strm.read(8192) 
    while (data) and (totl < size):
        file.write(data)
        totl += len(data)

        if (not qued) and ((skip == 'false') or (size > isad)):
            wait = int(_settings.getSetting('delay'))
            threading.Timer(wait, panQueue, (song, path)).start()
            qued = True

        if (totl >= size) or xbmc.abortRequested: break

        try: data = strm.read(8192)
        except: xbmc.log("%s.Fetch TIMEOUT (%s,%8d) '%s - %s'" % (_plugin, song.songId, totl, song.artist, song.title)) #, xbmc.LOGDEBUG)

    file.close()
    
    if totl < size:		# incomplete file
        xbmc.log("%s.Fetch RM (%s)          '%s - %s'" % (_plugin, song.songId, song.artist, song.title)) #, xbmc.LOGDEBUG)
        os.remove(path)
    elif totl <= isad:		# looks like an ad
        if skip == 'true':
            xbmc.log("%s.Fetch AD (%s)          '%s - %s'" % (_plugin, song.songId, song.artist, song.title)) #, xbmc.LOGDEBUG)
            os.remove(path)
        elif qued == False:
            song.artist = song.album = song.title = 'Advertisement'        
            path2 = path + '.ad.m4a'
            os.renames(path, path2)
            path = path2
            panQueue(song, path)

    else: panSave(song, path)


def panSong(song):
    lib = xbmc.translatePath(("%s/%s/%s - %s/%s - %s.m4a" % (_settings.getSetting('lib'), song.artist, song.artist, song.album, song.artist, song.title))).decode("utf-8")
    m4a = xbmc.translatePath(("%s/%s.m4a"                 % (_settings.getSetting('m4a'), song.songId))                                                  ).decode("utf-8")

    if not _settings.getSetting("img-%s" % song.stationId):	# Set Station Rhumb
        _settings.setSetting("img-%s" % song.stationId, song.artUrl)

    if os.path.isfile(lib):			# Found in Library
        xbmc.log("%s.Song LIB (%s)          '%s - %s'" % (_plugin, song.songId, song.artist, song.title))
        panQueue(song, lib)

    elif os.path.isfile(m4a):			# Found in Cache
        xbmc.log("%s.Song M4A (%s)          '%s - %s'" % (_plugin, song.songId, song.artist, song.title))
        panQueue(song, m4a)

    elif _settings.getSetting('mode') == '0':	# Stream Only
        qual = _settings.getSetting('quality')
        url  = song.audioUrl[qual]['audioUrl']
        panQueue(song, url)

    else:					# Cache / Save
        panFetch(song, m4a)


def panStrip(song):
    badc        = '\\/?%*:|"<>.'	# remove bad filename chars
    song.artist = ''.join(c for c in song.artist if c not in badc)
    song.album  = ''.join(c for c in song.album  if c not in badc)
    song.title  = ''.join(c for c in song.title  if c not in badc)

    return song


def panFill():
    global _station

    if not panAuth():
        if type(_station) is not Station: str = "%s.Fill NOAUTH (%s)" % _station[0]
        else:                             str = "%s.Fill NOAUTH (%s) '%s'" % (_station.id, _station.name)

        xbmc.log(str, xbmc.LOGWARNING)
        return

    if type(_station) is not Station: _station = _pandora.get_station_by_id(_station[0])

    try: songs = _station.get_playlist()
    except (PandoraTimeout, PandoraNetError): pass
    except (PandoraAuthTokenInvalid, PandoraAPIVersionError, PandoraError) as e:
        xbmcgui.Dialog().ok(_name, e.message, '', e.submsg)
        return

    for song in songs:
        song = panStrip(song)
        threading.Timer(0.01, panSong, (song,)).start()

    xbmc.log("%s.Fill  OK (%s,%8d)          '%s'" % (_plugin, _station.id, len(songs), _station.name), xbmc.LOGDEBUG)


def panPlay():
    _lock.acquire()
    threading.Thread(target = panFill).start()

    li = xbmcgui.ListItem(_station.name)
    li.setPath('special://home/addons/' + _plugin + '/empty.mp3')
    li.setProperty(_plugin, _stamp)

    start = time.time()

    while not _play:
        if xbmc.abortRequested:
            _lock.release()
            exit()
    
        xbmc.sleep(1000)
        if (threading.active_count() == 1) or ((time.time() - start) >= 60):
            xbmc.log("%s.Play BAD (%13s, %ds)" % (_plugin, _stamp, time.time() - start))
            xbmcgui.Dialog().ok(_name, 'No Tracks Received', '', 'Try again later')
            exit()

    _playlist.clear()
    _lock.release()
    time.sleep(0.01)	# yield to the song threads
    xbmc.sleep(1000)	# might return control to xbmc and skip the other threads ?

    xbmcplugin.setResolvedUrl(_handle, True, li)
    _player.play(_playlist)
    xbmc.executebuiltin('ActivateWindow(10500)')

    xbmc.log("%s.Play  OK (%13s,%27s) '%s'" % (_plugin, _stamp, _station.id, _station.name))


def panCheck():
    if (threading.active_count() == 1) and ((_playlist.size() - _playlist.getposition()) <= 1):
        threading.Thread(target = panFill).start()

    while (_playlist.size() > int(_settings.getSetting('listmax'))) and (_playlist.getposition() > 0):
        xbmc.executeJSONRPC('{"jsonrpc":"2.0", "id":1, "method":"Playlist.Remove", "params":{"playlistid":' + str(xbmc.PLAYLIST_MUSIC) + ', "position":0}}')

    if xbmcgui.getCurrentWindowId() == 10500:
        xbmc.executebuiltin("Container.Refresh")


def panExpire():
    m4a = xbmc.translatePath(_settings.getSetting('m4a')).decode("utf-8")
    exp = float(_settings.getSetting('expire')) * 3600.0

    regx = re.compile('^[a-z0-9]{32}\.')
    list = os.listdir(m4a)
    for file in list:
        if regx.match(file):
            file = "%s/%s" % (m4a, file)
            if os.stat(file).st_mtime < (time.time() - exp):
                xbmc.log("%s.Expire   (%s)" % (_plugin, file), xbmc.LOGDEBUG)
                os.remove(file)


def panLoop():
    while True:
        xbmc.sleep(5000)
        if xbmc.abortRequested: break

        _lock.acquire()
        try:
            if _playlist.getposition() >= 0:
                if _playlist[_playlist.getposition()].getProperty(_plugin) == _stamp:
                    panCheck()
                    _lock.release()
                    panExpire()

                else: 	# not our song in playlist, exit
                    _lock.release()
                    break	
        except: pass



# main
if _thumb is not None:
    img = xbmcgui.Dialog().browseSingle(2, 'Select Thumb', 'files', useThumbs = True)
    _settings.setSetting("img-%s" % _thumb[0], img)
    xbmc.executebuiltin("Container.Refresh")

elif _station is not None:
    for dir in [ 'm4a', 'lib' ]:
        dir = xbmc.translatePath(_settings.getSetting(dir)).decode("utf-8")
        if not os.path.isdir(dir): os.makedirs(dir)

    _brain.set_useragent("xbmc.%s" % _plugin, _version)

    panPlay()
    panLoop()
    xbmc.log("%s.Exit     (%13s)" % (_plugin, _stamp))

else: panDir()
