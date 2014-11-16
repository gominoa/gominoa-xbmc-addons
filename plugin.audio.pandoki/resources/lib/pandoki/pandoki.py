import collections, re, socket, sys, threading, time, urllib, urllib2
import xbmc, xbmcaddon, xbmcgui, xbmcplugin, xbmcvfs
import asciidamnit, musicbrainzngs, pithos

from mutagen.mp3 import MP3
from mutagen.easyid3 import EasyID3
from mutagen.easymp4 import EasyMP4



_addon	= xbmcaddon.Addon()
_base	= sys.argv[0]
_id	= _addon.getAddonInfo('id')
_stamp	= str(time.time())


def Log(msg, s = None, level = xbmc.LOGNOTICE):
    if s and s.get('artist'): xbmc.log("%s %s %s '%s - %s'" % (_id, msg, s['token'][-4:], s['artist'], s['title']), level) # song
    elif s:                   xbmc.log("%s %s %s '%s'"      % (_id, msg, s['token'][-4:], s['title']), level)              # station
    else:                     xbmc.log("%s %s"              % (_id, msg), level)


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
        self.station	= None
        self.stations	= None
        self.songs	= { }
        self.pithos	= pithos.Pithos()
        self.player	= xbmc.Player()
        self.playlist	= xbmc.PlayList(xbmc.PLAYLIST_MUSIC)
        self.ahead	= { }
        self.queue	= collections.deque()
        self.prof	= Val('prof')
        self.wait	= { 'auth' : 0, 'stations' : 0, 'flush' : 0, 'scan' : 0, 'next' : 0 }
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
            hand = urllib2.ProxyHandler({ 'http' : http, 'https' : http })
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

        try: self.pithos.connect(Val('one' + p), Val('username' + p), Val('password' + p))
        except pithos.PithosError:
            Log('Auth BAD')
            return False

        self.wait['auth'] = time.time() + (60 * 60)	# Auth every hour
        Log('Auth  OK')
        return True


    def Login(self):
        while not self.Auth():
            if xbmcgui.Dialog().yesno(Val('name'), '          Login Failed', 'Bad User / Pass / Proxy', '       Check Settings?'):
                xbmcaddon.Addon().openSettings()
            else:
                exit()


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
        elif sort == '1': stations = sorted(stations, key=lambda s: s['title'])	# A-Z

        stations.insert(0, quickmix)						# Quickmix back on top
        return stations


    def Dir(self, handle):
        self.Login()

        li = xbmcgui.ListItem('New Station ...')
        li.setIconImage(Val('icon'))
        li.setThumbnailImage(Val('icon'))
        xbmcplugin.addDirectoryItem(int(handle), "%s?search=hcraes" % _base, li, True)

        for s in self.Sorted():
            li = xbmcgui.ListItem(s['title'], s['token'])
            if self.station == s: li.select(True)

            art = Val("art-%s" % s['token'])
            if not art: art = s['art']
            li.setIconImage(art)
            li.setThumbnailImage(art)

            li.addContextMenuItems([('Rename Station', "RunPlugin(plugin://%s/?%s)" % (_id, urllib.urlencode({ 'rename' : s['token'], 'name' : s['title'] }))),
                                    ('Delete Station', "RunPlugin(plugin://%s/?%s)" % (_id, urllib.urlencode({ 'delete' : s['token'], 'name' : s['title'] }))),
                                    ('Select Thumb',   "RunPlugin(plugin://%s/?%s)" % (_id, urllib.urlencode({  'thumb' : s['token'], 'name' : s['title'] }))), ])

            xbmcplugin.addDirectoryItem(int(handle), "%s?%s" % (_base, urllib.urlencode({ 'play' : s['token'] })), li)

        xbmcplugin.endOfDirectory(int(handle), cacheToDisc = False)
        Log("Dir   OK %4s" % handle)


    def Search(self, handle, query):
        self.Login()

        for s in self.pithos.search(query, True):
            title = s['artist']
            title += (' - %s' % s['title']) if s.get('title') else ''

            li = xbmcgui.ListItem(title, s['token'])
            xbmcplugin.addDirectoryItem(int(handle), "%s?create=%s" % (_base, s['token']), li)

        xbmcplugin.endOfDirectory(int(handle), cacheToDisc = False)
        Log("Search   %4s '%s'" % (handle, query))


    def Info(self, s):
        info = { 'artist' : s['artist'], 'album' : s['album'], 'title' : s['title'] } #, 'rating' : s['rating'] }

        if s.get('duration'):
            info['duration'] = s['duration']

        return info


    def Add(self, song):
        li = xbmcgui.ListItem(song['artist'], song['title'], song['art'], song['art'])
        li.setProperty("%s.token" % _id, song['token'])
        li.setInfo('music', self.Info(song))

        if song.get('encoding') == 'm4a': li.setProperty('mimetype', 'audio/aac')
        if song.get('encoding') == 'mp3': li.setProperty('mimetype', 'audio/mpeg')

        self.playlist.add(song['path'], li)
        self.Scan(False)

        Log('Add   OK', song)

    
    def Queue(self, song):
        self.queue.append(song)


    def Msg(self, msg):
        if self.mesg == msg: return
        else: self.mesg = msg

        song = { 'token' : 'mesg', 'title' : msg, 'path' : self.silent, 'artist' : Val('name'),  'album' : Val('description'), 'art' : Val('icon') } #, 'rating' : '' }
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


    def Tag(self, song):
        try:
            res = musicbrainzngs.search_recordings(limit = 1, query = song['title'], artist = song['artist'], release = song['album'], qdur = str(song['duration'] * 1000))['recording-list'][0]
            song['number'] = int(res['release-list'][0]['medium-list'][1]['track-list'][0]['number'])
            song['count']  =     res['release-list'][0]['medium-list'][1]['track-count']
            song['score']  =     res['ext:score']
            song['brain']  =     res['id']

        except:
            song['score']  = '0'

        Log("Tag%4s%%" % song['score'], song)
        return song['score'] == '100'


    def Save(self, song):
        if (Val('mode') in ('0', '3')) or (song['title'] == 'Advertisement') or (song.get('save')) or (not self.Tag(song)): return

        tmp = "%s.%s" % (song['path'], song['encoding'])
        if not xbmcvfs.copy(song['path_cch'], tmp):
            Log('Save BAD', song)
            return

        if   song['encoding'] == 'm4a': tag = EasyMP4(tmp)
        elif song['encoding'] == 'mp3': tag = MP3(tmp, ID3 = EasyID3)

        if tag == None:
            Log('Save BAD', song)
            xbmcvfs.delete(tmp)
            return

        tag['tracknumber']         = "%d/%d" % (song['number'], song['count'])
        tag['musicbrainz_trackid'] = song['brain']
        tag['artist']              = song['artist']
        tag['album']               = song['album']
        tag['title']               = song['title']
        tag.save()

        xbmcvfs.mkdirs(song['path_dir'])
        xbmcvfs.copy(tmp, song['path_lib'])
        xbmcvfs.delete(tmp)
        song['save'] = True

        if (not xbmcvfs.exists(song['path_alb'])) or (not xbmcvfs.exists(song['path_art'])):
            try:
                strm = self.Proxy().open(song['art'])
                data = strm.read()
            except ValueError:
                Log("Save ART      '%s'" % song['art'])
                return

            for jpg in [ song['path_alb'], song['path_art'] ]:
                if not xbmcvfs.exists(jpg):
                    file = xbmcvfs.File(jpg, 'wb')
                    file.write(data)
                    file.close()

        Log('Save  OK', song, xbmc.LOGNOTICE)


    def Hook(self, song, size, totl):
        if totl in (341980, 340554, 173310):	# empty song cause requesting to fast
            self.Msg('Too Many Songs Requested')
            Log('Cache MT', song)
            return False

        if (song['title'] != 'Advertisement') and (totl <= int(Val('adsize')) * 1024):
            Log('Cache AD', song)

            song['artist'] = Val('name')
            song['album']  = Val('description')
            song['art']    = Val('icon')
            song['title']  = 'Advertisement'

            if (Val('skip') == 'true'):
                song['qued'] = True
                self.Msg('Skipping Advertisements')

        if (not song.get('qued')) and (size >= (song['bitrate'] / 8 * 1024 * int(Val('delay')))):
            song['qued'] = True
            self.Queue(song)

        return True


    def Cache(self, song):
        strm = self.Proxy().open(song['url'], timeout = 10)
        totl = int(strm.headers['Content-Length'])
        size = 0

        Log("%8d" % totl, song)

        cont = self.Hook(song, size, totl)
        if not cont: return

        file = xbmcvfs.File(song['path_cch'], 'wb')

        while (cont) and (size < totl) and (not xbmc.abortRequested) and (not self.abort):
            try: data = strm.read(min(8192, totl - size))
            except socket.timeout:
                Log('Cache TO', song)
                break

            file.write(data)
            size += len(data)
            cont = self.Hook(song, size, totl)

        file.close()
        strm.close()

        if (not cont) or (size != totl):
            xbmc.sleep(3000)
            xbmcvfs.delete(song['path_cch'])
            Log('Cache RM', song)

        else:
            self.Save(song)

        Log('Cache OK', song)


    def Fetch(self, song):
        if xbmcvfs.exists(song['path_lib']):	# Found in Library
            Log('Song LIB', song)
            song['path'] = song['path_lib']
            song['save'] = True
            self.Queue(song)

        elif xbmcvfs.exists(song['path_cch']):	# Found in Cache
            Log('Song CCH', song)
            song['path'] = song['path_cch']
            self.Queue(song)

        elif Val('mode') == '0':		# Stream Only
            Log('Song PAN', song)
            song['path'] = song['url']
            self.Queue(song)

        else:					# Cache / Save
            Log('Song GET', song)
            song['path'] = song['path_cch']
            self.Cache(song)


    def Seed(self, song):
        if not self.Stations(): return
        result = self.pithos.search("%s by %s" % (song['title'], song['artist']))[0]

        if (result['title'] == song['title']) and (result['artist'] == song['artist']):
            self.pithos.seed_station(song['station'], result['token'])
        else:
            Log('Seed BAD', song)


    def Branch(self, song):
        if not self.Stations(): return
        station = self.pithos.branch_station(song['token'])

        Prop('play', station['token'])
        Prop('action', 'play')

        Log('Branch  ', song)


    def Rate(self, song):
        Log("Rate %1s>%1s" % (song['rating'], song['rated']), song, xbmc.LOGNOTICE)

        song['rating'] = song['rated']
        expert = (Val('rating') == '1')

        if (song['rated'] == '5'):
            if (expert):
                self.Branch(song)
            else:
                self.pithos.add_feedback(song['token'], True)
            self.Save(song)

        elif (song['rated'] == '4'):
            if (expert):
                self.Seed(song)
            else:
                self.pithos.add_feedback(song['token'], True)
            self.Save(song)

        elif (song['rated'] == '3'):
            self.pithos.add_feedback(song['token'], True)
            self.Save(song)

        elif (song['rated'] == '2'):
            if (expert):
                self.pithos.set_tired(song['token'])
            else:
                self.pithos.add_feedback(song['token'], False)

        elif (song['rated'] == '1'):
            self.pithos.add_feedback(song['token'], False)

        elif (song['rated'] == ''):
            feedback = self.pithos.add_feedback(song['token'], True)
            self.pithos.del_feedback(song['station'], feedback)


    def Scan(self, rate = True):
        if (rate) and ((time.time() < self.wait['scan']) or (xbmcgui.getCurrentWindowDialogId() == 10135)): return
        self.wait['scan'] = time.time() + 15

        songs = dict()
        for pos in range(0, self.playlist.size()):
            tk = self.playlist[pos].getProperty("%s.token" % _id)
            rt = xbmc.getInfoLabel("MusicPlayer.Position(%d).Rating" % pos)

            if tk in self.songs:
                song = self.songs[tk]
                del self.songs[tk]
                songs[tk] = song

                if (rate) and (song.get('rating', rt) != rt):
                    song['rated'] = rt
                    self.Rate(song)
                elif not song.get('rating'):
                    song['rating'] = rt

        for s in self.songs:
            if (not self.songs[s].get('keep', False)) and xbmcvfs.exists(self.songs[s].get('path_cch')):
                xbmcvfs.delete(self.songs[s]['path_cch'])
                Log('Scan  RM', self.songs[s])

        self.songs = songs


    def Path(self, song):
        badc           = '\\/?%*:|"<>.'		# remove bad filename chars
        song['artist'] = ''.join(c for c in song['artist'] if c not in badc)
        song['album']  = ''.join(c for c in song['album']  if c not in badc)
        song['title']  = ''.join(c for c in song['title']  if c not in badc)

        song['path_cch'] = xbmc.translatePath(asciidamnit.asciiDammit("%s/%s - %s.%s"            % (Val('cache'),   song['artist'], song['title'],  song['encoding'])))
        song['path_dir'] = xbmc.translatePath(asciidamnit.asciiDammit("%s/%s/%s - %s"            % (Val('library'), song['artist'], song['artist'], song['album'])))
        song['path_lib'] = xbmc.translatePath(asciidamnit.asciiDammit("%s/%s/%s - %s/%s - %s.%s" % (Val('library'), song['artist'], song['artist'], song['album'], song['artist'], song['title'], song['encoding'])))
        song['path_alb'] = xbmc.translatePath(asciidamnit.asciiDammit("%s/%s/%s - %s/folder.jpg" % (Val('library'), song['artist'], song['artist'], song['album'])))
        song['path_art'] = xbmc.translatePath(asciidamnit.asciiDammit("%s/%s/folder.jpg"         % (Val('library'), song['artist']))) #.decode("utf-8")


    def Fill(self):
        token = self.station['token']
        if len(self.ahead.get(token, '')) > 0: return

        if not self.Auth():
            self.Msg('Login Failed. Check Settings')
            self.abort = True
            return

        try: songs = self.pithos.get_playlist(token, int(Val('quality')))
        except (pithos.PithosTimeout, pithos.PithosNetError): pass
        except (pithos.PithosAuthTokenInvalid, pithos.PithosAPIVersionError, pithos.PithosError) as e:
            Log("%s, %s" % (e.message, e.submsg))
            self.Msg(e.message)
            self.abort = True
            return

        for song in songs:
            self.Path(song)

        self.ahead[token] = collections.deque(songs)

        Log('Fill  OK', self.station)


    def Next(self):
        if time.time() < self.wait['next']: return
        self.wait['next'] = time.time() + float(Val('delay')) + 1

        self.Fill()

        token = self.station['token']
        if len(self.ahead.get(token, '')) > 0:
            song = self.ahead[token].popleft()
            threading.Timer(0, self.Fetch, (song,)).start()


    def List(self):
        if (not self.station) or (not self.player.isPlayingAudio()): return

        len  = self.playlist.size()
        pos  = self.playlist.getposition()
        item = self.playlist[pos]
        tokn = item.getProperty("%s.token" % _id)
        skip = xbmc.getInfoLabel("MusicPlayer.Position(%d).Rating" % pos)
        skip = ((tokn == 'mesg') or (skip == '1') or (skip == '2')) and (xbmcgui.getCurrentWindowDialogId() != 10135)

        if (len - pos) < 2:
            self.Next()

#        elif ((len - pos) < 2) and (tokn != 'mesg'):
#            self.Msg("Queueing %s" % self.station['title'])

        elif skip:
            self.player.playnext()


    def Deque(self):
        if len(self.queue) == 0: return
        elif self.once:
            self.playlist.clear()
            self.Flush()

        while len(self.queue) > 0:
            song = self.queue.popleft()
            self.Add(song)
            if song['token'] != 'mesg':
                self.songs[song['token']] = song

        if self.once:
            self.player.play(self.playlist)
            self.once = False 

        max = int(Val('history'))
        while (self.playlist.size() > max) and (self.playlist.getposition() > 0):
            xbmc.executeJSONRPC('{"jsonrpc":"2.0", "id":1, "method":"Playlist.Remove", "params":{"playlistid":' + str(xbmc.PLAYLIST_MUSIC) + ', "position":0}}')

        if xbmcgui.getCurrentWindowId() == 10500:
            xbmc.executebuiltin("Container.Refresh")


    def Tune(self, token):
        for s in self.Stations():
            if (token == s['token']) or (token == s['token'][-4:]):
                if self.station == s: return False

                self.station = s
                Val('station' + self.prof, token)
                return True

        return False


    def Play(self, token):
        if self.Tune(token):
            self.Fill()

            while True:
                len = self.playlist.size() - 1
                pos = self.playlist.getposition()
                if len > pos:
                    item = self.playlist[len]
                    tokn  = item.getProperty("%s.token" % _id)

                    if (self.station) and (tokn in self.songs):
                        self.songs[tokn]['keep'] = True
                        self.ahead[self.station['token']].appendleft(self.songs[tokn])

                    xbmc.executeJSONRPC('{"jsonrpc":"2.0", "id":1, "method":"Playlist.Remove", "params":{"playlistid":' + str(xbmc.PLAYLIST_MUSIC) + ', "position":' + str(len) + '}}')
                else: break

            self.Msg("Queuing %s" % self.station['title'])
            Log('Play  OK', self.station, xbmc.LOGNOTICE)

        xbmc.executebuiltin('ActivateWindow(10500)')


    def Create(self, token):
        self.Stations()
        station = self.pithos.create_station(token)

        Log('Create  ', station)
        self.Play(station['token'])


    def Delete(self, token):
        if (self.station) and (self.station['token'] == token): self.station = None

        self.Stations()
        station = self.pithos.delete_station(token)

        Log('Delete  ', station, xbmc.LOGNOTICE)
        xbmc.executebuiltin("Container.Refresh")


    def Rename(self, token, name):
        self.Stations()
        station = self.pithos.rename_station(token, name)

        Log('Rename  ', station)
        xbmc.executebuiltin("Container.Refresh")


    def Action(self):
        act = Prop('action')

        if _stamp != Prop('stamp'):
            self.abort = True
            self.station = None
            return

        elif act == 'search':
            self.Search(Prop('handle'), Prop('search'))

        elif act == 'create':
            self.Create(Prop('create'))

        elif act == 'rename':
            self.Rename(Prop('rename'), Prop('name'))

        elif act == 'delete':
            self.Delete(Prop('delete'))

        elif act == 'play':
            self.Play(Prop('play'))

        elif act == 'dir':
            self.Dir(Prop('handle'))
            if (self.once) and (Val('autoplay') == 'true') and (Val('station' + self.prof)):
                self.Play(Val('station' + self.prof))

        Prop('action', None)
        Prop('run', str(time.time()))


    def Flush(self):
        cch = xbmc.translatePath(Val('cache')).decode("utf-8")
        reg = re.compile('^.*\.(m4a|mp3)')

        (dirs, list) = xbmcvfs.listdir(cch)

        for file in list:
            if reg.match(file):
                xbmcvfs.delete("%s/%s" % (cch, file))
                Log("Flush OK      '%s'" % file)


    def Loop(self):
        while (not xbmc.abortRequested) and (not self.abort) and (self.once or self.player.isPlayingAudio()):
            time.sleep(0.01)
            xbmc.sleep(1000)

            self.Action()
            self.Deque()
            self.List()
            self.Scan()

        Log('Exit  OK', level = xbmc.LOGNOTICE)
        Prop('run', None)

