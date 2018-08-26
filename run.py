from src.gui.gui import GUI
from src.player import GUIPlayer
from src.database import Database
from src.keybinds import KB
from src.session import SessionManager
from src.settings import SettingsManager

import logging

logger = logging.getLogger('debug')
logger.setLevel(logging.DEBUG)
handler = logging.FileHandler(filename='debug.log', encoding='utf-8', mode='w')
handler.setFormatter(logging.Formatter('%(asctime)s:%(levelname)s:%(name)s: %(message)s'))
logger.addHandler(handler)

session = SessionManager()
db = Database(session)
settings = SettingsManager()
player = GUIPlayer(None, None, None, session, settings, GUIPlayer.SHUFFLED, db, 0.2)
keybinds = KB()
keybinds.add_keybind('alt+c', print, 'test', 'hello', global_=True)
keybinds.add_keybind('ctrl+3', player.play_next_song, 'next song', global_=True)
keybinds.add_keybind('subtract', player.change_volume, 'vol down', global_=True)
keybinds.add_keybind('add', player.change_volume,'vol up', True, global_=True)

gui = GUI('music player', 's0hvaperuna', settings, session, db, player, keybinds)

gui.show()

player.exit_player()
gui.main_window.metadata.stop()
keybinds.stop()
session.stop()
session.wait_for_stop(10)
db.database.close()
