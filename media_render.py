#!/usr/bin/env python3

import logging
import sys
from contextlib import contextmanager

import Ice
from Ice import identityToString as id2str

from gst_player import GstPlayer

Ice.loadSlice('-I{} spotifice_v1.ice'.format(Ice.getSliceDir()))
import Spotifice  # type: ignore # noqa: E402

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("MediaRender")

class MediaRenderI(Spotifice.MediaRender):
    def __init__(self, player):

        self.player = player
        self.server: Spotifice.MediaServerPrx = None
        self.current_track = None

        # Hito1: Estado de la playlist
        self.current_playlist = None
        self.playlist_index = 0
        self.history = []
        self.repeat = False
        self.paused = False

    def ensure_player_stopped(self):
        if self.player.is_playing():
            raise Spotifice.PlayerError(reason="Already playing")

    def ensure_server_bound(self):
        if not self.server:
            raise Spotifice.BadReference(reason="No MediaServer bound")

    # --- RenderConnectivity ---

    def bind_media_server(self, media_server, current=None):
        try:
            proxy = media_server.ice_timeout(500)
            proxy.ice_ping()
        except Ice.ConnectionRefusedException as e:
            raise Spotifice.BadReference(reason=f"MediaServer not reachable: {e}")

        self.server = media_server
        self.history = []           # reset history
        self.current_playlist = None
        logger.info(f"Bound to MediaServer '{id2str(media_server.ice_getIdentity())}'")

    def unbind_media_server(self, current=None):
        self.stop(current)
        self.server = None
        self.history = []
        self.current_playlist = None
        logger.info("Unbound MediaServer")

    # --- ContentManager ---

    def load_track(self, track_id, current=None):
        self.ensure_server_bound()
        with self.keep_playing_state(current):
            self.current_track = self.server.get_track_info(track_id)
            self.current_playlist = None
            self.history.append(self.current_track.id)
        logger.info(f"Current track set to: {self.current_track.title}")

    # Hito1: Cargar una playlist
    def load_playlist(self, playlist_id, current=None):
        self.ensure_server_bound()
        playlist = self.server.get_playlist(playlist_id)
        if not playlist.track_ids:
            raise Spotifice.PlaylistError(playlist_id, "Playlist is empty")

        with self.keep_playing_state(current):
            self.current_playlist = playlist
            self.playlist_index = 0
            first_track = self.current_playlist.track_ids[0]
            self.current_track = self.server.get_track_info(first_track)
            self.history = [self.current_track.id]  # reset history

        logger.info(f"Loaded playlist '{playlist.name}' (first track = {self.current_track.title})")

    def get_current_track(self, current=None):
        return self.current_track

    @contextmanager
    def keep_playing_state(self, current):
        # Recordar si estaba 'playing', no 'paused'
        was_playing = self.player.is_playing()

        if was_playing or self.paused:
            self.stop(current) # Esto también pone self.paused = False

        try:
            yield # Aquí es donde la pista cambia
        finally:
            
            if was_playing:
                self.play(current)

    def play(self, current=None):
        def get_chunk_hook(chunk_size):
            try:
                return self.server.get_audio_chunk(current.id, chunk_size)
            except Spotifice.IOError as e:
                logger.error(e)
            except Ice.Exception as e:
                logger.critical(e)

        assert current, "remote invocation required"
        self.ensure_server_bound()

    # Hito1: Reanudar la reproducción si estaba pausada
        if self.paused:
            self.paused = False
            self.player.resume()
            return

        if not self.current_track:
            raise Spotifice.TrackError(reason="No track loaded")

        self.server.open_stream(self.current_track.id, current.id)
        self.player.configure(get_chunk_hook)

        if not self.player.confirm_play_starts():
            raise Spotifice.PlayerError(reason="Failed to confirm playback")

    # Hito1: Pausar la reproducción
    def pause(self, current=None):
        # Definimos el estado 'playing' 
        is_in_playing_state = not self.paused and self.player.is_playing()

        if is_in_playing_state:
            self.player.pause()
            self.paused = True
            logger.info("Paused")
        else:
            # Si no está en playing, no se puede pausar 
            raise Spotifice.PlayerError(reason="Cannot pause, player is not PLAYING")

    def stop(self, current=None):
        if self.server and current:
            self.server.close_stream(current.id)

        self.paused = False

        if not self.player.stop():
            raise Spotifice.PlayerError(reason="Failed to confirm stop")

        logger.info("Stopped")

    # Hito1: Obtener el estado de reproducción
    def get_status(self, current=None):
        if self.paused:
            state = Spotifice.PlaybackState.PAUSED
        elif self.player.is_playing():
            state = Spotifice.PlaybackState.PLAYING
        else:
            state = Spotifice.PlaybackState.STOPPED
    
        return Spotifice.PlaybackStatus(
            state=state,
            repeat=self.repeat,
            current_track_id=self.current_track.id if self.current_track else ""
    )

    def next(self, current=None):
        assert current, "remote invocation required"

        if not self.current_playlist:
            logger.info("Next ignored: no playlist loaded.")
            return

        # Recordamos si está pausado antes de cambiar de pista
        was_paused = self.paused

        is_at_end = self.playlist_index >= len(self.current_playlist.track_ids) - 1

        if is_at_end and not self.repeat:
            logger.info("End of playlist, no repeat. Not advancing.")
            return

        if is_at_end and self.repeat:
            self.playlist_index = 0
        else:
            self.playlist_index += 1

        new_track_id = self.current_playlist.track_ids[self.playlist_index]

        self.ensure_server_bound()
        with self.keep_playing_state(current):
            self.current_track = self.server.get_track_info(new_track_id)
            self.history.append(self.current_track.id)

        if was_paused:
            self.paused = True

        logger.info(f"Next track: {self.current_track.title}")

    # Hito1: Pista anterior
    def previous(self, current=None):
        assert current, "remote invocation required"

        was_paused = self.paused

        if len(self.history) < 2:
            logger.info("Previous ignored: no more history.")
            return

        # Eliminamos la pista actual del histórico
        self.history.pop()
        prev_id = self.history[-1]

        self.ensure_server_bound()
        with self.keep_playing_state(current):
            self.current_playlist = None
            self.current_track = self.server.get_track_info(prev_id)
        
        if was_paused:
            self.paused = True

        logger.info(f"Previous track: {self.current_track.title}")

    # Hito1: Establecer el modo de repetición
    def set_repeat(self, value, current=None):  
        self.repeat = value                     
        logger.info(f"Repeat = {self.repeat}")


def main(ic, player):
    servant = MediaRenderI(player)

    adapter = ic.createObjectAdapter("MediaRenderAdapter")
    proxy = adapter.add(servant, ic.stringToIdentity("mediaRender1"))
    logger.info(f"MediaRender: {proxy}")

    adapter.activate()
    ic.waitForShutdown()

    logger.info("Shutdown")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("Usage: media_render.py <config-file>")

    player = GstPlayer()
    player.start()
    try:
        with Ice.initialize(sys.argv[1]) as communicator:
            main(communicator, player)
    except KeyboardInterrupt:
        logger.info("Server interrupted by user.")
    finally:
        player.shutdown()
