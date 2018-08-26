class FullSong:
    pass

class Tag:
    pass

class Playlist:
    pass


def add_by_tag(playlist, **selectors):
    m = Tag.songs.get_through_model()
    mm = Playlist.songs.get_through_model()

    tagged = (FullSong
              .select()
              .join(m)
              .where(**selectors))

    songs = (tagged.switch(FullSong)
             .select(FullSong.id)
             .join(mm).distinct()
             .where(mm.playlist_id == 1))

    songs = list(map(lambda s: s.id, songs))
    songs = tagged.switch(FullSong).where(FullSong.id.not_in(songs))

    def check(s):
        # Test that proves no duplicates exist
        for ss in songs:
            if ss.id == s.id:
                print(s.id)

    for s in playlist.songs:
        check(s)

    playlist.songs.add(songs)


import peewee
from playhouse.fields import ManyToManyField

db = peewee.SqliteDatabase(":memory:")


def max_sql_variables():
    """Get the maximum number of arguments allowed in a query by the current
    sqlite3 implementation. Based on `this question
    `_

    Returns
    -------
    int
        inferred SQLITE_MAX_VARIABLE_NUMBER
    """
    import sqlite3
    db = sqlite3.connect(':memory:')
    cur = db.cursor()
    cur.execute('CREATE TABLE t (test)')
    low, high = 0, 100000
    while (high - 1) > low:
        guess = (high + low) // 2
        query = 'INSERT INTO t VALUES ' + ','.join(['(?)' for _ in
                                                    range(guess)])
        args = [str(i) for i in range(guess)]
        try:
            cur.execute(query, args)
        except sqlite3.OperationalError as e:
            if "too many SQL variables" in str(e):
                high = guess
            else:
                raise
        else:
            low = guess
    cur.close()
    db.close()
    return low

SQLITE_MAX_VARIABLE_NUMBER = max_sql_variables()
print(SQLITE_MAX_VARIABLE_NUMBER)