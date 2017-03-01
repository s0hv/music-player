# Global variables
class GV:
    StartPlaying = 0
    NoAutoStart = 1
    MainQueue = 0
    SecondaryQueue = 1
    MarkedQueue = 2
    History = 3
    Queues = {MainQueue: 'main_queue',
              SecondaryQueue: 'secondary_queue',
              MarkedQueue: 'marked',
              History: 'history'}

    TableColumns = {'id': {}, 'title': {'editable': True, 'fallback': 'name'},
                    'artist': {'editable': True}, 'duration': {'editable': True},
                    'album': {'editable': True}, 'track': {'editable': True},
                    'year': {'editable': True}, 'band': {'editable': True},
                    'play_count': {'editable': True}, 'rating': {'editable': True}}


class DefaultSettings:
    Size = (1300, 900)
    Volume = 0.5
    WarnOnPlaylistDuplicate = True
    ConfirmTrackRemoval = True
    ConfirmQueueClear = True
    OnStartup = GV.StartPlaying
    DelayBetweenSongs = 0
    ScrollOnChange = True
