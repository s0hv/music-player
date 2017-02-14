class GV:
    StartPlaying = 0
    NoAutoStart = 1
    MainQueue = 0
    SecondaryQueue = 1
    MarkedQueue = 2
    Queues = {0: 'main_queue',
              1: 'secondary_queue',
              2: 'marked'}


class DefaultSettings:
    Size = (1300, 900)
    Volume = 0.5
    WarnOnPlaylistDuplicate = True
    ConfirmTrackRemoval = True
    ConfirmQueueClear = True
    OnStartup = GV.StartPlaying
    DelayBetweenSongs = 0
    ScrollOnChange = True
