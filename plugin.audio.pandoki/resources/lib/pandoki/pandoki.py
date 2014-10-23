import collections, re, socket, sys, threading, time, urllib, urllib2
import xbmc, xbmcaddon, xbmcgui, xbmcplugin, xbmcvfs
import musicbrainzngs, pithos
from mutagen.mp4 import MP4



_addon	= xbmcaddon.Addon()
_base	= sys.argv[0]
_id	= _addon.getAddonInfo('id')
_stamp	= str(time.time())


def Log(msg, level = xbmc.LOGNOTICE):
    xbmc.log("%s(%s) %s" % (_id, _stamp, msg), level)


def Val(key, val = None):
    if key in [ 'author', 'changelog', 'description', 'disclaimer', 'fanart', 'icon', 'id', 'name', 'path', 'profile', 'stars', 'summary', 'type', 'version' ]:
        return _addon.getAddonInfo(key)

    if val:      _addon.setSetting(key, val)
    else: return _addon.getSetting(key)


def Prop(key, val = 'get'):
    if val == 'get': return xbmcgui.Window(10000).getProperty("%s.%s" % (_id, key))
    else:                   xbmcgui.Window(10000).setProperty("%s.%s" % (_id, key), val)



class Pandoki(object):
    def __init__(self):
        run = Prop('run')
        if (run) and (time.time() < float(run) + 3): return

        Prop('run', str(time.time()))
        Prop('stamp', _stamp)

        self.once	= True
        self.abort	= False
        self.mesg	= None
        self.token	= None
        self.station	= None
        self.stations	= None
        self.songs	= { }
        self.track	= 1
        self.pithos	= pithos.Pithos()
        self.player	= xbmc.Player()
        self.playlist	= xbmc.PlayList(xbmc.PLAYLIST_MUSIC)
        self.queue	= collections.deque()
        self.prof	= Val('prof')
        self.wait	= { 'auth' : 0, 'stations' : 0, 'fill' : 0, 'flush' : 0, 'rate' : 0 }
        self.silent	= xbmc.translatePath("special://home/addons/%s/resources/media/silent.m4a" % _id)

        musicbrainzngs.set_useragent("xbmc.%s" % _id, Val('version'))
        xbmcvfs.mkdirs(xbmc.translatePath(Val('cache')).decode("utf-8"))
        xbmcvfs.mkdirs(xbmc.translatePath(Val('library')).decode("utf-8"))


    def Proxy(self):
        proxy = Val('proxy')

        if   proxy == '0':	# Global
            open = urllib2.build_opener()

        elif proxy == '1':	# None
            hand = urllib2.ProxyHandler({})
            open = urllib2.build_opener(hand)

        elif proxy == '2':	# Custom
            http = "http://%s:%s@%s:%s" % (Val('proxy_user'), Val('proxy_pass'), Val('proxy_host'), Val('proxy_port'))
            hand = urllib2.ProxyHandler({ 'http' : http })
            open = urllib2.build_opener(hand)

        return open


    def Auth(self):
        p = Val('prof')
        if self.prof != p:
            self.wait['auth'] = 0
            self.stations = None
            self.prof = p

        if time.time() < self.wait['auth']: return True

        self.pithos.set_url_opener(self.Proxy())

        try: self.pithos.connect(Val('pandoraone'), Val('username' + p), Val('password' + p))
        except pithos.PithosError:
            Log('Auth BAD')
            return False

        self.wait['auth'] = time.time() + (60 * 60)	# Auth every hour
        Log('Auth  OK')
        return True


    def Stations(self):
        if (self.stations) and (time.time() < self.wait['stations']):
            return self.stations

        if not self.Auth(): return None
        self.stations = self.pithos.get_stations()

        self.wait['stations'] = time.time() + (60 * 5)				# Valid for 5 mins
        return self.stations


    def Sorted(self):
        sort = Val('sort')
        
        stations = list(self.Stations())
        quickmix = stations.pop(0)						# Quickmix

        if   sort == '0': stations = stations					# Normal
        elif sort == '2': stations = stations[::-1]				# Reverse
        elif sort == '1': stations = sorted(stations, key=lambda s: s['name'])	# A-Z

        stations.insert(0, quickmix)						# Quickmix back on top
        return stations


    def Dir(self, handle):
        while not self.Auth():
            if xbmcgui.Dialog().yesno(Val('name'), '          Login Failed', 'Bad User / Pass / Proxy', '       Check Settings?'):
                xbmcaddon.Addon().openSettings()
            else: exit()

#        li = xbmcgui.ListItem("Quit %s" % Val('name'), _stamp)
#        li.setIconImage(Val('icon'))
#        li.setThumbnailImage(Val('icon'))
#        xbmcplugin.addDirectoryItem(int(handle), "%s?quit=%s" % (_base, _stamp), li)

        for station in self.Sorted():
            li = xbmcgui.ListItem(station['name'], station['token'])

            art = Val("art-%s" % station['token'])
            if not art: art = station['art']
            li.setIconImage(art)
            li.setThumbnailImage(art)

            li.addContextMenuItems([('Select Thumb', "RunPlugin(plugin://%s/?thumb=%s)" % (_id, station['token']))])

            xbmcplugin.addDirectoryItem(int(handle), "%s?play=%s" % (_base, station['token']), li)

        xbmcplugin.endOfDirectory(int(handle), cacheToDisc = False)
        Log("Dir   OK %4s" % handle)


    def Info(self, s):
        info = { 'artist' : s['artist'], 'album' : s['album'], 'title' : s['title'], 'rating' : s['rating'], 'tracknumber' : self.track }
        if s.get('duration'): info['duration'] = s['duration']

        return info

    def Add(self, song):
        li = xbmcgui.ListItem(song['artist'], song['title'], song['art'], song['art'])
        li.setProperty("%s.id" % _id, song['id'])
        li.setProperty('mimetype', 'audio/aac')
        li.setInfo('music', self.Info(song))

        self.playlist.add(song['path'], li)
        self.track += 1

        Log("Add   OK %s '%s - %s'" % (song['id'][:4], song['artist'], song['title']), xbmc.LOGNOTICE)

    
    def Queue(self, song):
        self.queue.append(song)


    def Msg(self, msg):
        if self.mesg == msg: return
        else: self.mesg = msg

        song = { 'id' : 'mesg', 'title' : msg, 'path' : self.silent, 'artist' : Val('name'),  'album' : Val('description'), 'art' : Val('icon'), 'rating' : '' }
        self.Queue(song)

#        while True:		# Remove old messages
#            item = None
#            for pos in range(0, self.playlist.getposition() - 1):
#                try: item = self.playlist[pos]
#                except RuntimeError:
#                    item = None
#                    break
#
#                id = item.getProperty("%s.id" % _id)
#                if (id == 'mesg'):
#                    xbmc.executeJSONRPC('{"jsonrpc":"2.0", "id":1, "method":"Playlist.Remove", "params":{"playlistid":' + str(xbmc.PLAYLIST_MUSIC) + ', "position":' + str(pos) + '}}')
#                    break
#
#            if not item:
#                break


    def Station(self, token = None):
        if (not token) and (self.station): return self.station

        for s in self.Stations():
            if token == s['token']:
                Val('station' + self.prof, token)
                self.token = token
                self.station = s
                return s


    def Tag(self, song, path):
        mp4 = MP4(path)
        dur = int(mp4.info.length * 1000)
        res = musicbrainzngs.search_recordings(limit = 1, query = song['title'], artist = song['artist'], release = song['album'], qdur = str(dur))['recording-list'][0]
        sco = res['ext:score']

#        song['duration'] = dur / 1000
#        song['score'] = sco
#        song['brain'] = res['id']

        Log("Tag%4s%% %s '%s - %s'" % (sco, song['id'][:4], song['artist'], song['title']))

        if sco == '100':
            mp4['----:com.apple.iTunes:MusicBrainz Track Id'] = res['id']
            mp4['\xa9ART'] = song['artist']
            mp4['\xa9alb'] = song['album']
            mp4['\xa9nam'] = song['title']
            mp4.save()
            return True
        
        return False


    def Save(self, song):
        if (song['title'] == 'Advertisement') or (song.get('save')): return

        dst = xbmc.translatePath(("%s/%s/%s - %s/%s - %s.m4a" % (Val('library'), song['artist'], song['artist'], song['album'], song['artist'], song['title']))).decode("utf-8")
        dir = xbmc.translatePath(("%s/%s/%s - %s"             % (Val('library'), song['artist'], song['artist'], song['album']))                               ).decode("utf-8")
        alb = xbmc.translatePath(("%s/%s/%s - %s/folder.jpg"  % (Val('library'), song['artist'], song['artist'], song['album']))                               ).decode("utf-8")
        art = xbmc.translatePath(("%s/%s/folder.jpg"          % (Val('library'), song['artist']))                                                              ).decode("utf-8")
        tmp = "%s.tmp" % song['path']

        if not xbmcvfs.copy(song['path'], tmp):
            Log("Save BAD %s '%s - %s'" % (song['id'][:4], song['artist'], song['title']))
            return

        if self.Tag(song, tmp):
            xbmcvfs.mkdirs(dir)
            xbmcvfs.copy(tmp, dst)

            try:
                if not xbmcvfs.exists(alb): urllib.urlretrieve(song['art'], alb)
                if not xbmcvfs.exists(art): urllib.urlretrieve(song['art'], art)
            except (IOError, UnicodeDecodeError): pass

            song['save'] = dst
            Log("Save  OK %s '%s - %s'" % (song['id'][:4], song['artist'], song['title']), xbmc.LOGNOTICE)

        xbmcvfs.delete(tmp)


    def Hook(self, song, size, totl):
        if totl in (341980, 173310):	# empty song cause requesting to fast
            self.Msg('To Many Songs Requested')
            Log("Fetch MT %s '%s - %s'" % (song['id'][:4], song['artist'], song['title']))
            return False

        if (song['title'] != 'Advertisement') and (totl <= int(Val('adsize')) * 1024):
            Log("Fetch AD %s '%s - %s'" % (song['id'][:4], song['artist'], song['title']))

            song['artist'] = Val('name')
            song['album']  = Val('description')
            song['art']    = Val('icon')
            song['title']  = 'Advertisement'

            if (Val('skip') == 'true'):
                song['qued'] = True
                self.Msg('Skipping Advertisements')

        if (not song.get('qued')) and (size >= int(Val('prefetch')) * 1024):
            song['qued'] = True
#            self.Tag(song)
            self.Queue(song)

        return True


    def Open(self, song):
        path = song['path']
        file = open(path, 'wb', 0)
        temp = "%s.tmp" % song['path']

        while not xbmcvfs.copy(path, temp):
            file.close()
            xbmcvfs.delete(path)

            Log("Open BAD %s '%s - %s'" % (song['id'][:4], song['artist'], song['title']))
            xbmc.sleep(1000)
            file = open(path, 'wb', 0)

        xbmcvfs.delete(temp)
        Log("Open  OK %s '%s - %s'" % (song['id'][:4], song['artist'], song['title']))

        return file


    def Cache(self, song):
        strm = urllib2.Request(song[Val('quality')])
        strm = self.Proxy().open(strm, timeout = 10)
        totl = int(strm.headers['Content-Length'])
        size = 0

        Log("%8d %s '%s - %s'" % (totl, song['id'][:4], song['artist'], song['title']))

        cont = self.Hook(song, size, totl)
        file = self.Open(song)

        while (cont) and (size < totl) and (not xbmc.abortRequested) and (not self.abort):
            try: data = strm.read(min(8192, totl - size))
            except socket.timeout:
                Log("Cache TO %s '%s - %s'" % (song['id'][:4], song['artist'], song['title']))
                break

            file.write(data)
            size += len(data)
            cont = self.Hook(song, size, totl)

        file.close()
        strm.close()

        if (not cont) or (size != totl):
            xbmc.sleep(3000)
            xbmcvfs.delete(song['path'])
            Log("Cache RM %s '%s - %s'" % (song['id'][:4], song['artist'], song['title']))

        elif (Val('mode') == '1') and (size == totl):
            self.Save(song)
            
        else:
            Log("Cache OK %s '%s - %s'" % (song['id'][:4], song['artist'], song['title']))


    def Fetch(self, song):
        lib = xbmc.translatePath(("%s/%s/%s - %s/%s - %s.m4a" % (Val('library'), song['artist'], song['artist'], song['album'], song['artist'], song['title']))).decode("utf-8")
        cch = xbmc.translatePath(("%s/%s - %s.m4a" % (Val('cache'), song['artist'], song['title']))).decode("utf-8")

#        if not Val("art-%s" % self.token):	# Set Station Thumb
#            Val("art-%s" % self.token, song['art'])

        if xbmcvfs.exists(lib):			# Found in Library
            Log("Song LIB %s '%s - %s'" % (song['id'][:4], song['artist'], song['title']))
            song['path'] = song['save'] = lib
#            self.Tag(song)
            self.Queue(song)

        elif xbmcvfs.exists(cch):		# Found in Cache
            Log("Song CCH %s '%s - %s'" % (song['id'][:4], song['artist'], song['title']))
            song['path'] = cch
#            self.Tag(song)
            self.Queue(song)

        elif Val('mode') == '0':		# Stream Only
            Log("Song PAN %s '%s - %s'" % (song['id'][:4], song['artist'], song['title']))
            song['path'] = song[Val('quality')]
            self.Queue(song)

        else:					# Cache / Save
            Log("Song GET %s '%s - %s'" % (song['id'][:4], song['artist'], song['title']))
            song['path'] = cch
            self.Cache(song)


    def Strip(self, song):
        badc           = '\\/?%*:|"<>.'		# remove bad filename chars
        song['artist'] = ''.join(c for c in song['artist'] if c not in badc)
        song['album']  = ''.join(c for c in song['album']  if c not in badc)
        song['title']  = ''.join(c for c in song['title']  if c not in badc)

        return song


    def Fill(self):
        if time.time() < self.wait['fill']: return

        if not self.Auth():
            self.Msg('Login Failed. Check Settings')
            self.abort = True
            return

        try: songs = self.pithos.get_playlist(self.token)
        except (pithos.PithosTimeout, pithos.PithosNetError): pass
        except (pithos.PithosAuthTokenInvalid, pithos.PithosAPIVersionError, pithos.PithosError) as e:
            Log("%s, %s" % (e.message, e.submsg))
            self.Msg(e.message)
            self.abort = True
            return

        for song in songs:
            song = self.Strip(song) 
            threading.Timer(0, self.Fetch, (song,)).start()

        self.wait['fill'] = time.time() + 60
        Log("Fill  OK %s '%s'" % (self.Station()['id'][-4:], self.Station()['name']))


    def Shrink(self):
        max = int(Val('history'))
        while (max >= 5) and (self.playlist.size() > max) and (self.playlist.getposition() > 0):
            xbmc.executeJSONRPC('{"jsonrpc":"2.0", "id":1, "method":"Playlist.Remove", "params":{"playlistid":' + str(xbmc.PLAYLIST_MUSIC) + ', "position":0}}')


    def Trunc(self):
#        while (self.playlist.size() > 0) and (self.playlist.getposition() != 0):
#            xbmc.executeJSONRPC('{"jsonrpc":"2.0", "id":1, "method":"Playlist.Remove", "params":{"playlistid":' + str(xbmc.PLAYLIST_MUSIC) + ', "position":0}}')
#
#        while (self.playlist.size() > 1):
#            xbmc.executeJSONRPC('{"jsonrpc":"2.0", "id":1, "method":"Playlist.Remove", "params":{"playlistid":' + str(xbmc.PLAYLIST_MUSIC) + ', "position":1}}')

        while True:
            len = self.playlist.size() - 1
            pos = self.playlist.getposition()
            if len > pos:
                xbmc.executeJSONRPC('{"jsonrpc":"2.0", "id":1, "method":"Playlist.Remove", "params":{"playlistid":' + str(xbmc.PLAYLIST_MUSIC) + ', "position":' + str(len) + '}}')
            else: break


    def Rate(self):
        if time.time() < self.wait['rate']: return
        self.wait['rate'] = time.time() + 15
    
        songs = dict()

        for pos in range(0, self.playlist.size()):
            id = self.playlist[pos].getProperty("%s.id" % _id)
            rt = xbmc.getInfoLabel("MusicPlayer.Position(%d).Rating" % pos)

            if id == 'mesg': continue

            if id in self.songs:
                song = self.songs[id]
                songs[id] = song

                if (song['rating'] != rt) and (song['rated'] == rt):
                    song['rating'] = rt
                    Log("Rated    %s '%s - %s'" % (song['id'][:4], song['artist'], song['title']))
                    print song
                    # got a legit change
                else: song['rated'] = rt

        self.songs = songs


    def List(self):
        if (not self.token) or (not self.player.isPlayingAudio()): return

        len = self.playlist.size()
        pos = self.playlist.getposition()
        left = len - pos - 1

        if left < 2:
            self.Fill()

        try: item = self.playlist[pos]
        except RuntimeError: return

        id = item.getProperty("%s.id" % _id)
        if (id != 'mesg') and (left == 0): self.Msg("Queueing %s" % self.Station()['name'])
        if (id == 'mesg') and (left  > 0): self.player.playnext()

#        Log("List  OK %s '%d / %d'" % (self.token[:4], pos + 1, len))


    def Deque(self):
        if len(self.queue) == 0: return
        elif self.once: self.playlist.clear()

        while len(self.queue) > 0:
            song = self.queue.popleft()
            self.Add(song)
            self.songs[song['id']] = song

        if self.once:
            self.player.play(self.playlist)
            self.once = False 

        self.Shrink()

        if xbmcgui.getCurrentWindowId() == 10500:
            xbmc.executebuiltin("Container.Refresh")


    def Play(self, token):
        if token != self.token:
            station = self.Station(token)
            self.wait['fill'] = 0
            self.Trunc()

            self.Msg("Queueing %s" % station['name'])
            Log("Play  OK %s '%s'" % (token[-4:], station['name']))

        xbmc.executebuiltin('ActivateWindow(10500)')


    def Props(self):
        Prop('run', str(time.time()))

        stamp = Prop('stamp')
#        quit = Prop('quit')
        play = Prop('play')
        dir = Prop('dir')

#        if quit or (stamp != _stamp):
#            self.abort = True
#            self.token = None
#            Prop('quit', None)
#            xbmc.executebuiltin('ActivateWindow(10000)')
#            return

        if play:
            self.Play(play)
            Prop('play', None)

        if dir:
            self.Dir(dir)
            Prop('dir', None)
            if (self.once) and (Val('autoplay') == 'true') and (Val('station' + self.prof)):
                self.Play(Val('station' + self.prof))


    def Flush(self):
        if time.time() < self.wait['flush']: return
        self.wait['flush'] = time.time() + (60 * 15)
    
        cch = xbmc.translatePath(Val('cache')).decode("utf-8")
        exp = time.time() - (float(Val('expire')) * 3600.0)
        reg = re.compile('^.*\.m4a')

        (dirs, list) = xbmcvfs.listdir(cch)

        for file in list:
            if reg.match(file):
                path = "%s/%s" % (cch, file)

                if xbmcvfs.Stat(path).st_mtime() < exp:
                    xbmcvfs.delete(path)
                    Log("Flush OK      '%s'" % file)


    def Loop(self):
        while (not xbmc.abortRequested) and (not self.abort) and (self.once or self.player.isPlayingAudio()):
            time.sleep(0.01)
            xbmc.sleep(1000)

            self.Flush()
            self.Props()
            self.Rate()
            self.Deque()
            self.List()

        Log('Exit  OK', xbmc.LOGNOTICE)

