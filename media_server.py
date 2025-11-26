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
    # Modificado para recibir referencia al servidor y poder borrarse de la lista
    def __init__(self, user_info, media_dir, tracks_db, server_impl, render_id_str):
        self.user_info = user_info
        self.media_dir = media_dir
        self.tracks_db = tracks_db
        self.server_impl = server_impl # Referencia al padre para callback de cierre
        self.render_id_str = render_id_str # ID del render asociado
        self.current_stream = None 

    def get_user_info(self, current=None):
        return self.user_info

    def open_stream(self, track_id, current=None):
        if track_id not in self.tracks_db:
             raise Spotifice.TrackError(track_id, "Track not found")

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
        logger.info(f"Closing session for user '{self.user_info.username}'")
        self.close_stream()
        
        # Avisa al servidor para que libere el render_id
        self.server_impl.remove_session(self.render_id_str)
        
        current.adapter.remove(current.id)


class MediaServerI(Spotifice.MediaServer):
    def __init__(self, media_dir, playlist_dir, users_file):
        self.media_dir = Path(media_dir)
        self.playlist_dir = Path(playlist_dir)
        self.users_file = Path(users_file)

        self.tracks = {}
        self.playlists = {}
        self.users_db = {} 
        
        # NUEVO: Diccionario para controlar sesiones activas
        # string(render_id), Valor: { 'username': str, 'proxy': obj }
        self.active_sessions = {}

        self.load_media()
        self.load_playlists()
        self.load_users()

    # (Métodos de carga load_media, load_playlists, load_users igual que antes) ...
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
                    id=data["id"], name=data["name"], 
                    description=data.get("description", ""), owner=data.get("owner", ""),
                    created_at=0, track_ids=valid_tracks
                )
                self.playlists[data["id"]] = playlist
            except Exception as e:
                logger.error(f"Error loading playlist {filepath.name}: {e}")
        logger.info(f"Loaded {len(self.playlists)} playlists")

    def load_users(self):
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

    # Método auxiliar para limpiar sesiones (llamado desde SecureStreamManagerI)
    def remove_session(self, render_id_str):
        if render_id_str in self.active_sessions:
            del self.active_sessions[render_id_str]
            logger.info(f"Session removed for render {render_id_str}")

    # AuthManager (HITO 2 MODIFICADO)
    def authenticate(self, media_render, username, password, current=None):
        logger.info(f"Auth attempt for user: {username}")
        
        if username not in self.users_db:
             raise Spotifice.AuthError(username, "User not found")
        
        user_data = self.users_db[username]
        
        calc = hashlib.md5((password + user_data["salt"]).encode('utf-8')).hexdigest()
        if not secrets.compare_digest(calc, user_data["digest"]):
            raise Spotifice.AuthError(username, "Invalid password")

        # 1. Obtener identidad del render como string único
        if not media_render:
             raise Spotifice.BadReference("Invalid MediaRender proxy")
        
        # Importante: Usar ice_getIdentity() para identificar al cliente unívocamente
        render_id_str = id2str(media_render.ice_getIdentity())

        # 2. Comprobar si ya existe sesión para este render
        if render_id_str in self.active_sessions:
            existing = self.active_sessions[render_id_str]
            
            # CASO: Auth same render twice (different user) -> ERROR
            if existing['username'] != username:
                raise Spotifice.AuthError(username, 
                    f"Render already in use by '{existing['username']}'. Close session first.")
            
            # CASO: Auth twice with same data -> DEVOLVER EXISTENTE
            logger.info(f"Returning existing session for {username}")
            return existing['proxy']

        # 3. Crear nueva sesión si no existe
        user_info = Spotifice.UserInfo(
            username=username,
            fullname=user_data["fullname"],
            email=user_data["email"],
            is_premium=user_data["is_premium"],
            created_at=0
        )

        # Pasamos 'self' y 'render_id_str' para que la sesión pueda auto-borrarse al cerrar
        stream_servant = SecureStreamManagerI(user_info, self.media_dir, self.tracks, self, render_id_str)
        
        proxy_id = Ice.stringToIdentity(f"session-{uuid.uuid4()}")
        proxy = current.adapter.add(stream_servant, proxy_id)
        secure_proxy = Spotifice.SecureStreamManagerPrx.uncheckedCast(proxy)
        
        # Guardar en diccionario de sesiones activas
        self.active_sessions[render_id_str] = {
            'username': username,
            'proxy': secure_proxy
        }
        
        logger.info(f"User '{username}' authenticated. Session created.")
        return secure_proxy


def main(ic):
    properties = ic.getProperties()
    media_dir = properties.getPropertyWithDefault('MediaServer.Content', 'media')
    playlist_dir = properties.getPropertyWithDefault('MediaServer.Playlists', 'playlists')
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