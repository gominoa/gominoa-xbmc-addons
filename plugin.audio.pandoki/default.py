import os, sys, time, urlparse
import xbmc, xbmcaddon, xbmcgui

path = xbmc.translatePath(xbmcaddon.Addon().getAddonInfo('path').decode('utf-8'))
path = xbmc.translatePath(os.path.join(path, 'resources', 'lib'))
sys.path.append(path)

from pandoki import *


handle	= sys.argv[1]
query	= urlparse.parse_qs(sys.argv[2][1:])

thumb	= query.get('thumb')[0] if query.get('thumb') else None
play	= query.get('play')[0]  if query.get('play')  else None
#quit	= query.get('quit')[0]  if query.get('quit')  else None


run = Prop('run') # only start up once
if (not run) or (float(run) < (time.time() - 3)):
    run = Pandoki()
else: run = False


def Wait(key, value):
    Prop(key, value)
    if run: return

    until = time.time() + 15
    while Prop(key) and (time.time() < until):
        xbmc.sleep(1000)


if thumb:
    img = xbmcgui.Dialog().browseSingle(2, 'Select Thumb', 'files', useThumbs = True)
    Val("img-%s" % thumb, img)
    xbmc.executebuiltin("Container.Refresh")            

if play:   Wait('play', play)
#elif quit: Wait('quit', quit)
else:      Wait('dir', handle)


if run: run.Loop()

