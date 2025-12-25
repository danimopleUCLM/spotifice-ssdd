#!/usr/bin/env python3

import sys
import time
import Ice
import IceStorm

# --- CARGAR V3 (OBLIGATORIO PARA HITO 3) ---
Ice.loadSlice('-I{} spotifice_v3.ice'.format(Ice.getSliceDir()))
import Spotifice  # type: ignore # noqa: E402

# --- CLASE LISTENER PARA EL BUSCADOR (HITO 3) ---
# Esta clase recibirá las respuestas asíncronas del servidor
class FinderListenerI(Spotifice.MediaFinderListener):
    def track_found(self, track, server_proxy, current=None):
        print(f"\n   [🔎 FINDER] ¡Pista encontrada!: '{track.title}' (ID: {track.id})")
        print(f"             Disponible en servidor: {server_proxy.ice_getIdentity().name}")

    def playlist_found(self, playlist, server_proxy, current=None):
        print(f"\n   [🔎 FINDER] ¡Playlist encontrada!: '{playlist.name}' (ID: {playlist.id})")
        print(f"             Disponible en servidor: {server_proxy.ice_getIdentity().name}")

def print_status(render, action_name=""):
    try:
        status = render.get_status()
        track = render.get_current_track()
        track_title = f"'{track.title}'" if track else "Ninguna"
        
        st_map = {
            Spotifice.PlaybackState.STOPPED: "STOPPED",
            Spotifice.PlaybackState.PLAYING: "PLAYING",
            Spotifice.PlaybackState.PAUSED: "PAUSED"
        }
        st_str = st_map.get(status.state, "UNKNOWN")
        print(f"   Status tras '{action_name}': {st_str} | Pista: {track_title}")
    except Exception as e:
        print(f"   Error obteniendo estado: {e}")

def main(ic):
    print("\n" + "="*60)
    print("      PRUEBA INTEGRAL SPOTIFICE (HITO 3)")
    print("="*60)

    # -----------------------------------------------------------
    # PASO 1: DESCUBRIMIENTO (MediaDirectory)
    # -----------------------------------------------------------
    print("\n>>> 1. [HITO 3] CONSULTANDO DIRECTORIO...")
    
    # Obtenemos el proxy del directorio del fichero de configuración
    proxy_dir_str = ic.getProperties().getProperty("MediaDirectory.Proxy")
    if not proxy_dir_str:
        print("❌ Error: Falta 'MediaDirectory.Proxy' en control.config")
        return

    try:
        directory = Spotifice.DirectoryPrx.checkedCast(ic.stringToProxy(proxy_dir_str))
        if not directory:
            print("❌ Error: No se pudo conectar al Directorio.")
            return

        # Obtenemos listas dinámicas
        servers_list = directory.get_media_servers()
        renders_list = directory.get_media_renders()

        print(f"   ✅ Servidores encontrados: {len(servers_list)}")
        print(f"   ✅ Renders encontrados:    {len(renders_list)}")

        if not servers_list or not renders_list:
            print("❌ DETENIENDO: Faltan componentes. Asegúrate de ejecutar media_server y media_render.")
            return

        # Seleccionamos automáticamente el primero de cada lista
        server = servers_list[0]
        render = renders_list[0]
        print(f"   -> Usaremos Servidor: {server.ice_getIdentity().name}")
        print(f"   -> Usaremos Render:   {render.ice_getIdentity().name}")

    except Exception as e:
        print(f"❌ Error crítico en Directorio: {e}")
        return

    # -----------------------------------------------------------
    # PASO 2: BÚSQUEDA (IceStorm Finder)
    # -----------------------------------------------------------
    print("\n>>> 2. [HITO 3] PROBANDO BUSCADOR (FinderTopic)...")
    
    topic_mgr_str = ic.getProperties().getProperty("IceStorm.TopicManager.Proxy")
    if topic_mgr_str:
        try:
            topic_mgr = IceStorm.TopicManagerPrx.checkedCast(ic.stringToProxy(topic_mgr_str))
            topic_name = ic.getProperties().getPropertyWithDefault("Finder.TopicName", "FinderTopic")
            
            # Obtenemos el tema (debe existir si el servidor arrancó bien)
            try:
                topic = topic_mgr.retrieve(topic_name)
            except IceStorm.NoSuchTopic:
                # Si no existe, lo creamos nosotros para la prueba
                topic = topic_mgr.create(topic_name)

            finder_pub = Spotifice.MediaFinderPrx.uncheckedCast(topic.getPublisher())

            # Crear listener local para recibir la respuesta
            adapter = ic.createObjectAdapterWithEndpoints("FinderAdapter", "tcp")
            listener = FinderListenerI()
            listener_prx = Spotifice.MediaFinderListenerPrx.uncheckedCast(adapter.addWithUUID(listener))
            adapter.activate()

            # LANZAR BÚSQUEDA: Asegúrate de que este fichero exista en tu carpeta media/
            # Si tienes los ficheros del enunciado, usa "Portal2-01-Science_is_Fun.mp3"
            track_query = "Portal2-01-Science_is_Fun.mp3" 
            print(f"   Enviando búsqueda asíncrona de: '{track_query}'...")
            finder_pub.find_track(track_query, listener_prx)
            
            # Esperamos un poco a que llegue la respuesta (ya que es asíncrono)
            time.sleep(2)
            
        except Exception as e:
            print(f"   ⚠️  Error en prueba Finder: {e}")
    else:
        print("   ⚠️  Saltando Finder: Falta 'IceStorm.TopicManager.Proxy' en config.")

    # -----------------------------------------------------------
    # PASO 3: AUTENTICACIÓN (Hito 2)
    # -----------------------------------------------------------
    print("\n>>> 3. [HITO 2] AUTENTICACIÓN...")
    try:
        # Usamos credenciales por defecto (asegúrate de que users.json las tenga)
        print("   Autenticando usuario 'user'...")
        session = server.authenticate(render, "user", "secret")
        print("   ✅ Sesión obtenida correctamente.")
        
        print("   Vinculando Render con Servidor y Sesión...")
        render.bind_media_server(server, session)
        
    except Spotifice.AuthError as e:
        print(f"❌ Fallo de autenticación: {e.reason}")
        return
    except Exception as e:
        print(f"❌ Error en enlace: {e}")
        return

    # -----------------------------------------------------------
    # PASO 4: REPRODUCCIÓN (Hito 1)
    # -----------------------------------------------------------
    print("\n>>> 4. [HITO 1] PRUEBA DE REPRODUCCIÓN...")
    
    try:
        # A) Cargar Playlist
        playlists = server.get_all_playlists()
        if playlists:
            p = playlists[0]
            print(f"   Cargando playlist: '{p.name}'")
            render.load_playlist(p.id)
            print_status(render, "Load Playlist")
            
            # B) Play
            print("   ▶️  PLAY")
            render.play()
            time.sleep(3) # Dejamos sonar 3 segundos
            print_status(render, "Playing")

            # C) Pause
            print("   ⏸️  PAUSE")
            render.pause()
            time.sleep(1)
            print_status(render, "Paused")

            # D) Stop
            print("   ⏹️  STOP")
            render.stop()
            print_status(render, "Stopped")
        else:
            print("   ⚠️  No hay playlists disponibles para probar.")

    except Exception as e:
        print(f"❌ Error durante la reproducción: {e}")

    # -----------------------------------------------------------
    # FINALIZAR
    # -----------------------------------------------------------
    print("\n>>> 5. LIMPIEZA")
    try:
        render.unbind_media_server()
        print("   ✅ Render desvinculado.")
    except: pass
    
    print("="*60)
    print("      PRUEBA COMPLETADA")
    print("="*60)

if __name__ == '__main__':
    # Cargamos control.config por defecto si no se pasa nada
    config = sys.argv[1] if len(sys.argv) > 1 else "control.config"
    with Ice.initialize(["--Ice.Config=" + config]) as ic:
        main(ic)