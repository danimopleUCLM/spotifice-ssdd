[["underscore"]]
#include <Ice/Identity.ice>

module Spotifice {
    class TrackInfo {
        string id;
        string title;
        string filename;
    };

    sequence<byte> AudioChunk;
    sequence<TrackInfo> TrackInfoSeq;

    exception Error {
        optional(1) string item;
        string reason;
    };

    exception IOError extends Error{};
    exception BadIdentity extends Error{};
    exception BadReference extends Error{};
    exception PlayerError extends Error{};
    exception StreamError extends Error{};
    exception TrackError extends Error{};
    exception PlaylistError extends Error{};
    exception AuthError extends Error{};

    interface MusicLibrary {
        TrackInfoSeq get_all_tracks() throws IOError;
        TrackInfo get_track_info(string track_id) throws IOError, TrackError;
    };

    sequence<string> TrackIdSeq;

    struct Playlist {
        string id;
        string name;
        string description;
        string owner;
        long created_at;
        TrackIdSeq track_ids;
    };

    sequence<Playlist> PlaylistSeq;

    interface PlaylistManager {
        idempotent PlaylistSeq get_all_playlists();
        idempotent Playlist get_playlist(string playlist_id) throws PlaylistError;
    };

    struct UserInfo {
        string username;
        string fullname;
        string email;
        bool is_premium;
        long created_at;
    };

    interface Session {
        idempotent UserInfo get_user_info();
        idempotent void close();
    };

    ["deprecate:StreamManager is deprecated, use authenticate()"]
    interface StreamManager {};

    interface SecureStreamManager extends Session {
        idempotent void open_stream(string track_id) throws IOError, TrackError;
        idempotent void close_stream();
        AudioChunk get_audio_chunk(int chunk_size) throws IOError, StreamError;
    };

    interface MediaServer;
    interface MediaRender;

    interface AuthManager {
        SecureStreamManager* authenticate(
            MediaRender* media_render, string username, string password)
            throws AuthError, BadReference;
    };

    // new in version 3
    interface MediaFinderListener {
        void track_found(TrackInfo track_info, MediaServer* media_server);
        void playlist_found(Playlist playlist, MediaServer* media_server);
    };

    // new in version 3
    interface MediaFinder {
        void find_track(string track_id, MediaFinderListener* listener);
        void find_playlist(string playlist_id, MediaFinderListener* listener);
    };

    interface MediaServer extends MusicLibrary, PlaylistManager, AuthManager, MediaFinder {};

    enum PlaybackState {
        STOPPED,
        PLAYING,
        PAUSED
    };

    class PlaybackStatus {
        PlaybackState state;
        string current_track_id;
        bool repeat;
    };

    interface RenderConnectivity {
        idempotent void bind_media_server(
            MediaServer* media_server, SecureStreamManager* stream_manager)
            throws BadReference;
        idempotent void unbind_media_server();
    };

    interface ContentManager {
        idempotent TrackInfo get_current_track();
        idempotent void load_track(string track_id)
            throws BadReference, PlayerError, StreamError, TrackError;
        idempotent void load_playlist(string playlist_id)
            throws PlaylistError, TrackError, PlayerError;
    };

    interface PlaybackController {
        void play() throws BadReference, IOError, PlayerError, StreamError, TrackError;
        idempotent void stop() throws PlayerError;
        void pause() throws PlayerError;
        idempotent PlaybackStatus get_status();
        void next() throws PlaylistError;
        void previous() throws PlaylistError;
        idempotent void set_repeat(bool value);
    };

    interface MediaRender extends PlaybackController, ContentManager, RenderConnectivity {};

    // new in version 3
    interface AnnounceListener {
        void server_up(Object* proxy);
        void server_down(Object* proxy);
    };

    sequence<MediaServer*> MediaServerPrxSeq;
    sequence<MediaRender*> MediaRenderPrxSeq;

    // new in version 3
    interface Directory {
        MediaServerPrxSeq get_media_servers();
        MediaRenderPrxSeq get_media_renders();
    };

    interface MediaDirectory extends AnnounceListener, Directory {};
};
