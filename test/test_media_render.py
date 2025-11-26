from gst_player import GstPlayer
from media_render import Spotifice
from media_render import main as render_main
from media_server import main as server_main

from .icetest import IceTestCase


class TestRender(IceTestCase):
    def setUp(self):
        import random
        self.server_port = random.randint(10000, 15000)
        self.render_port = random.randint(15001, 20000)
       
        import os
        cwd = os.getcwd()
        users_file_path = os.path.join(cwd, 'users.json')
       
        server_props = {
            'MediaServerAdapter.Endpoints': f'tcp -p {self.server_port}',
            'MediaServer.Content': 'test/media',
            'MediaServer.UsersFile': users_file_path}
        server_endpoint = f'mediaServer1:default -p {self.server_port} -t 500'
        self.create_server(server_main, server_props)

        player = GstPlayer()
        player.start()
        self.addCleanup(player.shutdown)

        render_props = {
            'MediaRenderAdapter.Endpoints': f'tcp -p {self.render_port}'}
        render_enpoint = f'mediaRender1:default -p {self.render_port} -t 500'
        self.create_server(render_main, render_props, player)

        self.server = self.create_proxy(server_endpoint, Spotifice.MediaServerPrx)
        self.sut = self.create_proxy(render_enpoint, Spotifice.MediaRenderPrx)


class PlaybackTests(TestRender):
    def test_id(self):
        self.assertEqual(self.sut.ice_id(), '::Spotifice::MediaRender')

    def test_stop_is_idempotent(self):
        self.sut.stop()
        self.sut.stop()

    def test_play_unbound_server(self):
        with self.assertRaises(Spotifice.BadReference) as cm:
            self.sut.play()

        self.assertEqual(cm.exception.reason, "No MediaServer bound")

    def test_play_unloaded_track(self):
        self.sut.bind_media_server(self.server, None)

        with self.assertRaises(Spotifice.TrackError) as cm:
            self.sut.play()

        self.assertEqual(cm.exception.reason, "No track loaded")

    def test_normal_play(self):
        tracks = self.server.get_all_tracks()
        sm = self.server.authenticate(self.sut, 'user', 'secret')
        self.sut.bind_media_server(self.server, sm)
        self.sut.load_track(tracks[1].id)

        self.sut.play()

    def test_can_not_play_if_player_busy(self):
        tracks = self.server.get_all_tracks()
        sm = self.server.authenticate(self.sut, 'user', 'secret')
        self.sut.bind_media_server(self.server, sm)
        self.sut.load_track(tracks[1].id)

        self.sut.play()

        with self.assertRaises(Spotifice.PlayerError) as cm:
            self.sut.play()

        self.assertEqual(cm.exception.reason, "Already playing")

class AuthTests(TestRender):
    def test_secure_play(self):
        secure_stream_mngr = self.server.authenticate(self.sut, 'user', 'secret')
        self.sut.bind_media_server(self.server, secure_stream_mngr)
        self.sut.load_track('2s.mp3')
        self.sut.play()

    def test_auth_idempotency(self):
        # Regla 2: Mismo usuario -> Misma sesión (no error)
        sm1 = self.server.authenticate(self.sut, 'user', 'secret')
        sm2 = self.server.authenticate(self.sut, 'user', 'secret')
        self.assertEqual(sm1, sm2)

    def test_auth_conflict(self):
        # Regla 1: Usuario diferente en sesión activa -> AuthError
        self.server.authenticate(self.sut, 'user', 'secret')
        with self.assertRaises(Spotifice.AuthError):
            self.server.authenticate(self.sut, 'jdoe', 'secret')
