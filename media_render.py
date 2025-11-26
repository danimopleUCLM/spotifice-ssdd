#!/usr/bin/env python3

import logging
import sys
from contextlib import contextmanager

import Ice
from Ice import identityToString as id2str

from gst_player import GstPlayer

# HITO 2: Cargamos la versión 2
Ice.loadSlice('-I{} spotifice_v2.ice'.format(Ice.getSliceDir()))
import Spotifice  # type: ignore # noqa: E402

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("MediaRender")

class MediaRenderI(Spotifice.MediaRender):
    def __init__(self, player):
        self.player = player
        self.server: Spotifice.MediaServerPrx = None
        
        # HITO 2: Guardamos la sesión segura aquí
        self.stream_manager: Spotifice.SecureStreamManagerPrx = None

        self.current_track = None
        self.current_playlist = None
        self.playlist_index = 0
        self.history = []
        self.repeat = False
        self.paused = False

    def ensure_server_bound(self):
        if not self.server:
            raise Spotifice.BadReference(reason="No MediaServer bound")
    
    # HITO 2: Añado stream_manager=None para compatibilidad
    def bind_media_server(self, media_server, stream_manager=None, current=None):
        try:
            media_server.ice_timeout(3000).ice_ping()
            # Si nos pasan un stream_manager (Hito 2), lo probamos también
            if stream_manager:
                stream_manager.ice_timeout(3000).ice_ping()
        except Ice.ConnectionRefusedException as e:
            raise Spotifice.BadReference(reason=f"MediaServer not reachable: {e}")

        self.server = media_server
        self.stream_manager = stream_manager # Guardamos la sesión
        
        self.history = []
        self.current_playlist = None
        
        # Log informativo
        auth_msg = " (Authenticated)" if stream_manager else ""
        logger.info(f"Bound to MediaServer '{id2str(media_server.ice_getIdentity())}'{auth_msg}")

    def unbind_media_server(self, current=None):
        self.stop(current)
        
        # HITO 2: Cerramos la sesión si existe
        if self.stream_manager:
            try:
                self.stream_manager.close()
            except Exception: pass

        self.server = None
        self.stream_manager = None
        self.history = []
        self.current_playlist = None
        logger.info("Unbound MediaServer")

    def load_track(self, track_id, current=None):
        self.ensure_server_bound()
        with self.keep_playing_state(current):
            self.current_track = self.server.get_track_info(track_id)
            self.current_playlist = None
            self.history.append(self.current_track.id)
        logger.info(f"Current track set to: {self.current_track.title}")

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
        was_playing = self.player.is_playing()

        if was_playing or self.paused:
            self.stop(current) 

        try:
            yield 
        finally:
            if was_playing:
                self.play(current)

    # PlaybackController

    def play(self, current=None):
        def get_chunk_hook(chunk_size):
            try:
                # HITO 2: Uso stream_manager en lugar de server
                if self.stream_manager:
                    return self.stream_manager.get_audio_chunk(chunk_size)
                else:
                    # Fallback por si los tests antiguos no autentican (aunque fallará en v2)
                    logger.error("No Authentication Session found!")
                    raise Spotifice.StreamError("NoAuth", "Authentication required")
            except Spotifice.IOError as e:
                logger.error(e)
            except Ice.Exception as e:
                logger.critical(e)

        assert current, "remote invocation required"
        self.ensure_server_bound()

        if self.paused:
            self.paused = False
            self.player.resume()
            logger.info("Resumed")
            return

        if self.player.is_playing():
            raise Spotifice.PlayerError(reason="Already playing")

        if not self.current_track:
            raise Spotifice.TrackError(reason="No track loaded")

        # HITO 2: Validación de sesión
        if not self.stream_manager:
            raise Spotifice.PlayerError(reason="Authentication required for streaming")

        # HITO 2: open_stream sobre la sesión (sin argumentos)
        self.stream_manager.open_stream(self.current_track.id)
        
        self.player.configure(get_chunk_hook)

        if not self.player.confirm_play_starts():
            raise Spotifice.PlayerError(reason="Failed to confirm playback")

    def pause(self, current=None):
        is_in_playing_state = not self.paused and self.player.is_playing()

        if is_in_playing_state:
            self.player.pause()
            self.paused = True
            logger.info("Paused")
        else:
            raise Spotifice.PlayerError(reason="Cannot pause, player is not PLAYING")

    def stop(self, current=None):
        # HITO 2: Cerramos stream en la sesión
        if self.stream_manager:
            try:
                self.stream_manager.close_stream()
            except Exception: pass

        self.paused = False

        if not self.player.stop():
            logger.warning("Player.stop() no confirmó, puede que ya estuviera parado.")
        else:
            logger.info("Stopped")

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

    def previous(self, current=None):
        assert current, "remote invocation required"
        
        was_paused = self.paused

        if len(self.history) < 2:
            logger.info("Previous ignored: no more history.")
            return

        self.history.pop()
        prev_id = self.history[-1]

        self.ensure_server_bound()
        with self.keep_playing_state(current):
            self.current_playlist = None 
            self.current_track = self.server.get_track_info(prev_id)
        
        if was_paused:
            self.paused = True

        logger.info(f"Previous track: {self.current_track.title}")

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