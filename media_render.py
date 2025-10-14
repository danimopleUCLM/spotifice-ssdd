#!/usr/bin/env python3

import logging
import sys
from contextlib import contextmanager

import Ice
from Ice import identityToString as id2str

from gst_player import GstPlayer

Ice.loadSlice('-I{} spotifice_v0.ice'.format(Ice.getSliceDir()))
import Spotifice  # type: ignore # noqa: E402

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("MediaRender")


class MediaRenderI(Spotifice.MediaRender):
    def __init__(self, player):
        self.player = player
        self.server: Spotifice.MediaServerPrx = None
        self.current_track = None

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
        logger.info(f"Bound to MediaServer '{id2str(media_server.ice_getIdentity())}'")

    def unbind_media_server(self, current=None):
        self.stop(current)
        self.server = None
        logger.info("Unbound MediaServer")

    # --- ContentManager ---

    def load_track(self, track_id, current=None):
        self.ensure_server_bound()

        try:
            with self.keep_playing_state(current):
                self.current_track = self.server.get_track_info(track_id)

            logger.info(f"Current track set to: {self.current_track.title}")

        except Spotifice.TrackError as e:
            logger.error(f"Error setting track: {e.reason}")
            raise

    def get_current_track(self, current=None):
        return self.current_track

    # --- PlaybackController ---

    @contextmanager
    def keep_playing_state(self, current):
        playing = self.player.is_playing()
        if playing:
            self.stop(current)
        try:
            yield
        finally:
            if playing:
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

        self.ensure_player_stopped()
        self.ensure_server_bound()

        if not self.current_track:
            raise Spotifice.TrackError(reason="No track loaded")

        try:
            self.server.open_stream(self.current_track.id, current.id)
        except Spotifice.BadIdentity as e:
            logger.error(f"Error starting stream: {e.reason}")
            raise Spotifice.StreamError(reason="Strean setup failed")

        self.player.configure(get_chunk_hook)
        if not self.player.confirm_play_starts():
            raise Spotifice.PlayerError(reason="Failed to confirm playback")

    def stop(self, current=None):
        if self.server and current:
            self.server.close_stream(current.id)

        if not self.player.stop():
            raise Spotifice.PlayerError(reason="Failed to confirm stop")

        logger.info("Stopped")


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
