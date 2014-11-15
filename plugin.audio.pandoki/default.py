import os, sys, time, urlparse
import xbmc, xbmcaddon, xbmcgui

path = xbmc.translatePath(xbmcaddon.Addon().getAddonInfo('path').decode('utf-8'))
path = xbmc.translatePath(os.path.join(path, 'resources', 'lib'))
sys.path.append(path)

from pandoki import *

def Wait(key, value):
    Prop(key, value)
    if run: return

    until = time.time() + 15
    while Prop(key) and (time.time() < until):
        xbmc.sleep(1000)


handle	= sys.argv[1]
query	= urlparse.parse_qs(sys.argv[2][1:])

search	= query.get('search')[0] if query.get('search') else None
create	= query.get('create')[0] if query.get('create') else None
rename	= query.get('rename')[0] if query.get('rename') else None
delete	= query.get('delete')[0] if query.get('delete') else None
thumb	= query.get( 'thumb')[0] if query.get('thumb')  else None
name	= query.get(  'name')[0] if query.get('name')   else None
play	= query.get(  'play')[0] if query.get('play')   else None


run = Prop('run') # only start up once
if (not run) or (float(run) < (time.time() - 3)):
    run = Pandoki()
else: run = False


if search:
    if search == 'hcraes':
        search = xbmcgui.Dialog().input('%s - Search' % Val('name'), Prop('search'))
        Prop('search', search)

    Prop('handle', handle)
    Wait('action', 'search')

elif create:
    Prop('create', create)
    Wait('action', 'create')

elif rename:
    name = xbmcgui.Dialog().input('%s - Search' % Val('name'), name)
    Prop('name', name)
    Prop('rename', rename)
    Wait('action', 'rename')

elif delete and xbmcgui.Dialog().yesno('%s - Delete Station' % Val('name'), 'Are you sure you want to delete?', '', name):
    Prop('delete', delete)
    Wait('action', 'delete')

elif thumb:
    img = xbmcgui.Dialog().browseSingle(2, 'Select Thumb', 'files', useThumbs = True)
    Val("art-%s" % thumb, img)
    xbmc.executebuiltin("Container.Refresh")            

elif play:
    Prop('play', play)
    Wait('action', 'play')

else:
    Prop('handle', handle)
    Wait('action', 'dir')

if run:    run.Loop()

