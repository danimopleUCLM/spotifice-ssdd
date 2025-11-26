import Ice

from media_server import Spotifice, main

from .icetest import IceTestCase


class TestServer(IceTestCase):
    def setUp(self):
        import random
        import os
        self.server_port = random.randint(20000, 25000)
       
        cwd = os.getcwd()
        users_file_path = os.path.join(cwd, 'users.json')

        server_props = {
            'MediaServerAdapter.Endpoints': f'tcp -p {self.server_port}',
            'MediaServer.Content': 'test/media',
            'MediaServer.UsersFile': users_file_path
        }
        server_endpoint = f'mediaServer1:default -p {self.server_port} -t 500'
        self.create_server(main, server_props)
        self.sut = self.create_proxy(server_endpoint, Spotifice.MediaServerPrx)


class MusicLibraryTests(TestServer):
    def test_get_all_tracks(self):
        tracks = self.sut.get_all_tracks()
        self.assertEqual(len(tracks), 4)
        self.assertEqual(tracks[0].id, '1s.mp3')

    def test_get_track_info(self):
        track = self.sut.get_track_info('1s.mp3')
        self.assertEqual(track.id, '1s.mp3')
        self.assertEqual(track.title, '1s')

    def test_get_track_info_wrong_track(self):
        with self.assertRaises(Spotifice.TrackError) as cm:
            self.sut.get_track_info('bad-track-id')

        self.assertEqual(cm.exception.item, 'bad-track-id')
        self.assertEqual(cm.exception.reason, 'Track not found')


class StreamManagerTests(TestServer):
    def setUp(self):
        super().setUp()
        render_id = Ice.Identity(name='test-render', category='')
        self.render_prx = Spotifice.MediaRenderPrx.uncheckedCast(
            self.client_ic.stringToProxy("test-render"))
        self.sm = self.sut.authenticate(self.render_prx, "user", "secret")

    def test_open_stream_wrong_track(self):
        track_id = 'bad-track-id'

        with self.assertRaises(Spotifice.TrackError) as cm:
            self.sm.open_stream(track_id)

        self.assertEqual(cm.exception.item, 'bad-track-id')
        self.assertEqual(cm.exception.reason, 'Track not found')

    def test_get_audio_chunk(self):
        track_id = self.sut.get_all_tracks()[0].id

        self.sm.open_stream(track_id)
        chunk = self.sm.get_audio_chunk(1024)

        self.assertGreater(len(chunk), 0)

        with open('test/media/1s.mp3', 'rb') as f:
            expected = f.read(len(chunk))
            self.assertEqual(chunk, expected)

    def test_get_audio_chunk_not_open_stream(self):
        with self.assertRaises(Spotifice.StreamError) as cm:
            self.sm.get_audio_chunk(1024)

        self.assertEqual(cm.exception.reason, 'No open stream for this session')
