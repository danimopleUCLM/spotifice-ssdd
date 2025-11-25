#!/usr/bin/env python3

import logging
import sys
import json
import hashlib
import secrets
import uuid
from pathlib import Path

import Ice
from Ice import identityToString as id2str

# HITO 2: Cargo la versión 2
Ice.loadSlice('-I{} spotifice_v2.ice'.format(Ice.getSliceDir()))
import Spotifice  # type: ignore # noqa: E402

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("MediaServer")


class StreamedFile:
    def __init__(self, track_info, media_dir):
        self.track = track_info
        filepath = media_dir / track_info.filename

        try:
            self.file = open(filepath, 'rb')
        except Exception as e:
            raise Spotifice.IOError(track_info.filename, f"Error opening media file: {e}")

    def read(self, size):
        return self.file.read(size)

    def close(self):
        try:
            if self.file:
                self.file.close()
        except Exception as e:
            logger.error(f"Error closing file for track '{self.track.id}': {e}")

    def __repr__(self):
        return f"<StreamState '{self.track.id}'>"


class SecureStreamManagerI(Spotifice.SecureStreamManager):
    
    # HITO 2: Nueva clase que maneja el streaming autenticado.
    # Hereda la lógica que antes tenía en MediaServerI para gestionar ficheros.
    
    def __init__(self, user_info, media_dir, tracks_db):
        self.user_info = user_info
        self.media_dir = media_dir
        self.tracks_db = tracks_db
        # En v2, la sesión maneja UN stream activo a la vez, el render solo reproduce uno.
        self.current_stream = None 

    def get_user_info(self, current=None):
        return self.user_info

    def open_stream(self, track_id, current=None):
        # Lógica adaptada del Hito 1 sin necesitar render_id
        if track_id not in self.tracks_db:
             raise Spotifice.TrackError(track_id, "Track not found")

        # Si ya hay uno abierto en esta sesión, lo cerramos antes
        self.close_stream(current)

        track_info = self.tracks_db[track_id]
        try:
            self.current_stream = StreamedFile(track_info, self.media_dir)
            logger.info(f"Stream opened for user '{self.user_info.username}' -> Track: {track_id}")
        except Exception as e:
             raise Spotifice.IOError(track_id, str(e))

    def close_stream(self, current=None):
        if self.current_stream:
            self.current_stream.close()
            self.current_stream = None
            logger.info(f"Closed stream for user '{self.user_info.username}'")

    def get_audio_chunk(self, chunk_size, current=None):
        if not self.current_stream:
             raise Spotifice.StreamError("NoStream", "No open stream for this session")

        try:
            data = self.current_stream.read(chunk_size)
            if not data:
                logger.info(f"Track exhausted: '{self.current_stream.track.id}'")
                self.close_stream(current)
            return data
        except Exception as e:
             raise Spotifice.IOError(self.current_stream.track.filename, f"Error reading file: {e}")

    def close(self, current=None):
        # Cierra la sesión y destruye este objeto remoto.
        logger.info(f"Closing session for user '{self.user_info.username}'")
        self.close_stream()
        current.adapter.remove(current.id)


class MediaServerI(Spotifice.MediaServer):
    def __init__(self, media_dir, playlist_dir, users_file):
        self.media_dir = Path(media_dir)
        self.playlist_dir = Path(playlist_dir)
        self.users_file = Path(users_file)

        self.tracks = {}
        # self.active_streams = {}  <-- ELIMINADO: Ahora lo gestiona SecureStreamManagerI
        self.playlists = {}
        self.users_db = {} 

        self.load_media()
        self.load_playlists()
        self.load_users()

    def ensure_track_exists(self, track_id):
        if track_id not in self.tracks:
            raise Spotifice.TrackError(track_id, "Track not found")

    def load_media(self):
        for filepath in sorted(Path(self.media_dir).iterdir()):
            if not filepath.is_file() or filepath.suffix.lower() != ".mp3":
                continue
            self.tracks[filepath.name] = self.track_info(filepath)

        logger.info(f"Loaded {len(self.tracks)} tracks")

    @staticmethod
    def track_info(filepath):
        return Spotifice.TrackInfo(
            id=filepath.name,
            title=filepath.stem,
            filename=filepath.name
        )

    def load_playlists(self):
        import json

        for filepath in sorted(self.playlist_dir.iterdir()):
            if not filepath.is_file() or filepath.suffix.lower() != ".playlist":
                continue

            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)

                valid_tracks = [tid for tid in data["track_ids"] if tid in self.tracks]

                playlist = Spotifice.Playlist(
                    id=data["id"],
                    name=data["name"],
                    description=data.get("description", ""),
                    owner=data.get("owner", ""),
                    created_at=0,
                    track_ids=valid_tracks
                )

                self.playlists[data["id"]] = playlist
                logger.info(f"Playlist cargada '{data['id']}' con {len(valid_tracks)} pistas")

            except Exception as e:
                logger.error(f"Error loading playlist {filepath.name}: {e}")

        logger.info(f"Loaded {len(self.playlists)} playlists")

    def load_users(self):
        # HITO 2: Carga de usuarios
        if not self.users_file.exists():
            logger.warning(f"Users file not found: {self.users_file}")
            return
        
        try:
            with open(self.users_file, "r", encoding="utf-8") as f:
                self.users_db = json.load(f)
            logger.info(f"Loaded {len(self.users_db)} users from {self.users_file}")
        except Exception as e:
            logger.error(f"Error loading users file: {e}")

    def get_all_tracks(self, current=None):
        return list(self.tracks.values())

    def get_track_info(self, track_id, current=None):
        self.ensure_track_exists(track_id)
        return self.tracks[track_id]

    def get_all_playlists(self, current=None):
        return list(self.playlists.values())

    def get_playlist(self, playlist_id, current=None):
        if playlist_id not in self.playlists:
            raise Spotifice.PlaylistError(playlist_id, "Playlist not found")
        return self.playlists[playlist_id]

    # StreamManager (ELIMINADO AQUÍ, MOVIDO A SecureStreamManagerI) 

    # AuthManager (HITO 2)
    def authenticate(self, media_render, username, password, current=None):
        logger.info(f"Auth attempt for user: {username}")
        
        if username not in self.users_db:
             raise Spotifice.AuthError(username, "User not found")
        
        user_data = self.users_db[username]
        
        # Verificación según PDF
        calc = hashlib.md5((password + user_data["salt"]).encode('utf-8')).hexdigest()
        if not secrets.compare_digest(calc, user_data["digest"]):
            raise Spotifice.AuthError(username, "Invalid password")

        user_info = Spotifice.UserInfo(
            username=username,
            fullname=user_data["fullname"],
            email=user_data["email"],
            is_premium=user_data["is_premium"],
            created_at=0
        )

        # FACTORÍA: Crear nueva sesión y registrarla dinámicamente
        stream_servant = SecureStreamManagerI(user_info, self.media_dir, self.tracks)
        proxy_id = Ice.stringToIdentity(f"session-{uuid.uuid4()}")
        proxy = current.adapter.add(stream_servant, proxy_id)
        
        logger.info(f"User '{username}' authenticated. Session: {id2str(proxy_id)}")
        return Spotifice.SecureStreamManagerPrx.uncheckedCast(proxy)


def main(ic):
    properties = ic.getProperties()
    media_dir = properties.getPropertyWithDefault('MediaServer.Content', 'media')
    playlist_dir = properties.getPropertyWithDefault('MediaServer.Playlists', 'playlists')
    
    # HITO 2: Propiedad obligatoria para los tests automáticos
    users_file = properties.getPropertyWithDefault('MediaServer.UsersFile', 'users.json')

    adapter = ic.createObjectAdapter("MediaServerAdapter")

    servant = MediaServerI(Path(media_dir), Path(playlist_dir), Path(users_file))

    proxy = adapter.add(servant, ic.stringToIdentity("mediaServer1"))
    logger.info(f"MediaServer: {proxy}")

    adapter.activate()
    ic.waitForShutdown()

    logger.info("Shutdown")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("Usage: media_server.py <config-file>")

    try:
        with Ice.initialize(sys.argv[1]) as communicator:
            main(communicator)
    except KeyboardInterrupt:
        logger.info("Server interrupted by user.")