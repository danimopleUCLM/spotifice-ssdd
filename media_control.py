#!/usr/bin/env python3

import sys
from time import sleep

import Ice

# --- IMPORTANTE: Cargar la v1 del slice ---
Ice.loadSlice('-I{} spotifice_v1.ice'.format(Ice.getSliceDir()))
import Spotifice  # type: ignore # noqa: E402


def get_proxy(ic, property, cls):
    
    #Función de utilidad para obtener un proxy de forma robusta.
    
    proxy = ic.propertyToProxy(property)
    if proxy is None:
        print(f"Error: Propiedad '{property}' no encontrada en el config.")
        return None
        
    print(f"Obteniendo proxy para: {proxy}")

    for _ in range(5):
        try:
            proxy.ice_ping()
            print(f"Conexión exitosa con {property}")
            break
        except Ice.ConnectionRefusedException:
            print(f"Conexión rechazada para {property}, reintentando...")
            sleep(0.5)
    else:
        print(f"Error: No se pudo conectar a {property}")
        return None

    obj = cls.checkedCast(proxy)
    if obj is None:
        raise RuntimeError(f'Proxy inválido para {property}')

    return obj


def print_status(render, test_name=""):
    # Imprime el estado actual del reproductor.
    try:
        status = render.get_status()
        track = render.get_current_track()
        track_title = f"'{track.title}'" if track else "Ninguna"
        
        print(f"  [{test_name}] Estado: {status.state} | Repetir: {status.repeat} | Pista: {track_title}")
        return status, track

    except Exception as e:
        print(f"Error obteniendo estado: {e}")
        return None, None

def test_exception(func, expected_exception, test_name):
    #Función de utilidad para probar excepciones.
    try:
        func()
        print(f"  [ERROR] {test_name}: Se esperaba {expected_exception.__name__}, pero no falló.")
    except expected_exception as e:
        print(f"  [ÉXITO] {test_name}: Se recibió {expected_exception.__name__} correctamente: {e.reason}")
    except Exception as e:
        print(f"  [ERROR] {test_name}: Se esperaba {expected_exception.__name__}, pero se recibió: {e}")


def main(ic):
    try:
        # --- 1. Obtener Proxies ---
        print("--- 1. Conectando con Servidores ---")
        server = get_proxy(ic, 'MediaServer.Proxy', Spotifice.MediaServerPrx)
        render = get_proxy(ic, 'MediaRender.Proxy', Spotifice.MediaRenderPrx)

        if not server or not render:
            print("Error: No se pudieron obtener los proxies. Abortando.")
            return

        # --- 2. Enlazar y Limpiar ---
        print("\n--- 2. Enlazando y Limpiando Estado ---")
        render.bind_media_server(server)
        render.stop() # Asegurarse de que está parado

        # --- 3. Probar PlaylistManager (MediaServer) ---
        print("\n--- 3. Probando PlaylistManager (Hito 1.1) ---")
        playlists = server.get_all_playlists()
        if not playlists:
            print("  [ERROR] No se encontraron playlists. Asegúrate de que media_server.py se está ejecutando.")
            return
        print(f"  Se encontraron {len(playlists)} playlists.")
        
        p1 = server.get_playlist(playlists[0].id)
        p2 = server.get_playlist(playlists[1].id)
        print(f"  Éxito al obtener playlist '{p1.name}'")

        # --- 4. Probar Regla 1b: load_playlist NO reproduce ---
        print("\n--- 4. Probando Regla 1b (load_playlist no reproduce) ---")
        render.load_playlist(p1.id)
        status, track = print_status(render, "load_playlist")
        if status.state != Spotifice.PlaybackState.STOPPED:
             print(f"  [ERROR] El estado debería ser STOPPED, pero es {status.state}")
        if track.id != p1.track_ids[0]:
             print(f"  [ERROR] Debería estar cargada la Pista 1, pero está {track.id}")
        print("  [ÉXITO] load_playlist carga la pista y se mantiene STOPPED.")

        # --- 5. Probar Play / Pause / Resume ---
        print("\n--- 5. Probando Play / Pause / Resume ---")
        print("Iniciando reproducción (play)...")
        render.play()
        sleep(4)
        print_status(render, "play")

        print("\nPausando (pause)...")
        render.pause()
        sleep(4)
        status, _ = print_status(render, "pause")
        if status.state != Spotifice.PlaybackState.PAUSED:
             print(f"  [ERROR] El estado debería ser PAUSED, pero es {status.state}")

        print("\nReanudando (con play)...")
        render.play()
        sleep(4)
        status, _ = print_status(render, "resume")
        if status.state != Spotifice.PlaybackState.PLAYING:
             print(f"  [ERROR] El estado debería ser PLAYING, pero es {status.state}")

        # --- 6. Probar Next / Previous / Repeat ---
        print("\n--- 6. Probando Next / Previous / Repeat ---")
        print("Siguiente pista (next)...")
        render.next() # Pista 2
        sleep(4)
        print_status(render, "next 1")
        
        print("\nSiguiente pista (next)...")
        render.next() # Pista 3
        sleep(4)
        print_status(render, "next 2")

        print("\nPista anterior (previous)...")
        render.previous() # Pista 2
        sleep(4)
        print_status(render, "previous")
        
        print("\nActivando repetición...")
        render.set_repeat(True)
        print_status(render, "repeat on")
        render.set_repeat(False)
        print_status(render, "repeat off")

        # --- 7. Probar Reglas de Comportamiento (Las más importantes) ---
        print("\n--- 7. Probando Reglas de Comportamiento (Hito 1.4) ---")

        print("\nProbando Regla 1a (Mantener estado PAUSED):")
        render.load_playlist(p1.id) # Cargamos P1 de nuevo (H=[T1])
        render.next()               # H=[T1, T2]
        render.play()               # Tocando T2
        sleep(4)
        render.pause()              # Pausado en T2
        print_status(render, "Prev-Test")
        print("...ejecutando next() mientras está en PAUSA:")
        render.next()               # Carga T3 (H=[T1, T2, T3])
        status, track = print_status(render, "Post-Test")
        if status.state != Spotifice.PlaybackState.PAUSED:
            print(f"  [ERROR] El estado DEBE seguir PAUSED, pero es {status.state}")
        if track.id != p1.track_ids[2]:
            print(f"  [ERROR] La pista DEBE ser la T3, pero es {track.id}")
        print("  [ÉXITO] El estado se mantuvo PAUSED y la pista cambió.")
        
        print("\nProbando Regla 1a (Mantener estado STOPPED):")
        render.stop() # Parado en T3
        print("...ejecutando previous() mientras está en STOP:")
        render.previous() # Carga T2 (H=[T1, T2, T3, T2]) -> ¡OJO! previous() BORRA LA PLAYLIST
        status, track = print_status(render, "Post-Test")
        if status.state != Spotifice.PlaybackState.STOPPED:
            print(f"  [ERROR] El estado DEBE seguir STOPPED, pero es {status.state}")
        print("  [ÉXITO] El estado se mantuvo STOPPED y la pista cambió.")

        print("\nProbando Regla (previous borra la playlist):")
        print("...ejecutando next() después de previous():")
        render.next() # No debería hacer NADA, porque previous() borró la playlist
        status_post, track_post = print_status(render, "Post-Test")
        if track.id != track_post.id:
            print(f"  [ERROR] La pista NO debería haber cambiado (T2), pero cambió a {track_post.id}")
        print("  [ÉXITO] next() no hizo nada porque la playlist se borró correctamente.")

        # --- 8. Probar Regla 1c (stop() reinicia la pista) ---
        print("\n--- 8. Probando Regla 1c (stop() vs pause()) ---")
        render.play()
        print("...reproduciendo 3 segundos...")
        sleep(3)
        render.pause()
        print("...pausado 3 segundos...")
        sleep(3)
        print("...reanudando (debe seguir desde el segundo 3)...")
        render.play()
        sleep(3)
        print("...deteniendo (stop)...")
        render.stop()
        sleep(3)
        print("...reproduciendo de nuevo (debe sonar desde el segundo 0)...")
        render.play()
        sleep(3)
        print("  [ÉXITO] Prueba de stop() completada.")

        # --- 9. Probar Escenario de la Profesora (Histórico) ---
        print("\n--- 9. Probando Escenario de la Profesora (Histórico) ---")
        render.stop()
        
        print(f"...Cargando Playlist '{p1.name}' (H=[T1])")
        render.load_playlist(p1.id) # H=[P1-T1]
        
        print("...next() (H=[T1, T2])")
        render.next() # H=[P1-T1, P1-T2]
        
        print(f"...Cargando Pista Individual '{p2.track_ids[0]}' (H=[T1, T2, T3])")
        render.load_track(p2.track_ids[0]) # H=[P1-T1, P1-T2, P2-T1]
        
        status, track = print_status(render, "Prev-Test")
        print("...invocando previous()...")
        render.previous() # Carga P1-T2
        
        status_post, track_post = print_status(render, "Post-Test")
        if track_post.id != p1.track_ids[1]:
            print(f"  [ERROR] Debería sonar '{p1.track_ids[1]}', pero suena '{track_post.id}'")
        else:
            print(f"  [ÉXITO] El histórico funciona: se reproduce '{track_post.title}'")

        # --- 10. Probar Errores de 'pause' ---
        print("\n--- 10. Probando Errores de 'pause' (Regla 2) ---")
        render.play()
        sleep(1)
        render.pause()
        print_status(render, "PAUSED")
        test_exception(render.pause, Spotifice.PlayerError, "Pausar estando en PAUSED")
        
        render.stop()
        print_status(render, "STOPPED")
        test_exception(render.pause, Spotifice.PlayerError, "Pausar estando en STOPPED")

        # --- 11. Limpieza ---
        print("\n--- 11. Deteniendo y desenlazando ---")
        render.stop()
        render.unbind_media_server()
        print("\nPrueba del Hito 1 completada (Versión Mejorada).")

    except Exception as e:
        print(f"\nHa ocurrido un error inesperado: {e}")
        if isinstance(e, Ice.Exception):
            print(e)
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    if len(sys.argv) < 2:
        sys.exit("Usage: media_control.py <config-file>")

    try:
        with Ice.initialize(sys.argv[1]) as communicator:
            main(communicator)
    except KeyboardInterrupt:
        print("Interrumpido por el usuario.")
    except Exception as e:
        print(f"Error en la inicialización de Ice: {e}")
        sys.exit(1)