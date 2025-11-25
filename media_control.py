#!/usr/bin/env python3

import sys
from time import sleep
import Ice

# --- CARGAR V2 (HITO 2) ---
Ice.loadSlice('-I{} spotifice_v2.ice'.format(Ice.getSliceDir()))
import Spotifice  # type: ignore # noqa: E402


def get_proxy(ic, property, cls):
    proxy = ic.propertyToProxy(property)
    if proxy is None:
        print(f"Error: Propiedad '{property}' no encontrada.")
        return None
    try:
        proxy.ice_ping()
        return cls.checkedCast(proxy)
    except Exception:
        return None

def print_status(render, test_name=""):
    try:
        status = render.get_status()
        track = render.get_current_track()
        track_title = f"'{track.title}'" if track else "Ninguna"
        
        # Mapeo de estados para que sea legible
        st_map = {
            Spotifice.PlaybackState.STOPPED: "STOPPED",
            Spotifice.PlaybackState.PLAYING: "PLAYING",
            Spotifice.PlaybackState.PAUSED: "PAUSED"
        }
        st_str = st_map.get(status.state, "UNKNOWN")
        
        print(f"  [{test_name}] Estado: {st_str} | Repetir: {status.repeat} | Pista: {track_title}")
        return status, track
    except Exception as e:
        print(f"Error obteniendo estado: {e}")
        return None, None

def test_exception(func, expected_exception, test_name):
    try:
        func()
        print(f"  [ERROR] {test_name}: Se esperaba {expected_exception.__name__}, pero NO falló.")
    except expected_exception as e:
        print(f"  [ÉXITO] {test_name}: Se recibió {expected_exception.__name__} correctamente. Razón: {e.reason if hasattr(e, 'reason') else ''}")
    except Exception as e:
        print(f"  [ERROR] {test_name}: Se esperaba {expected_exception.__name__}, pero se recibió: {type(e).__name__}")


def main(ic):
    print("--- 1. Conectando con Servidores (Hito 2) ---")
    server = get_proxy(ic, 'MediaServer.Proxy', Spotifice.MediaServerPrx)
    render = get_proxy(ic, 'MediaRender.Proxy', Spotifice.MediaRenderPrx)

    if not server or not render:
        print("Error crítico de conexión.")
        return

    # =======================================================
    # PASO CLAVE HITO 2: AUTENTICACIÓN
    # =======================================================
    print("\n--- 2. Autenticación y Enlace Seguro ---")
    try:
        print("Autenticando usuario 'user'...")
        session = server.authenticate(render, "user", "secret")
        print("✅ Autenticación correcta. Sesión obtenida.")
        
        print("Enlazando Render con la Sesión...")
        render.bind_media_server(server, session)
        
        # Nos aseguramos de empezar limpios
        render.stop()
        
    except Spotifice.AuthError as e:
        print(f"❌ Error de Autenticación: {e.reason}")
        return
    except Exception as e:
        print(f"❌ Error al enlazar: {e}")
        return

    # =======================================================
    # A PARTIR DE AQUÍ: TODAS LAS PRUEBAS DEL HITO 1
    # =======================================================
    try:
        # --- 3. Probar PlaylistManager ---
        print("\n--- 3. Probando PlaylistManager (Hito 1) ---")
        playlists = server.get_all_playlists()
        if not playlists:
            print("  [AVISO] No hay playlists.")
            return
        
        p1 = server.get_playlist(playlists[0].id)
        # Intentamos coger una segunda playlist si existe, si no usamos la misma
        p2 = server.get_playlist(playlists[1].id) if len(playlists) > 1 else p1
        
        print(f"  Playlists encontradas: {len(playlists)}")
        print(f"  Usando playlist principal: '{p1.name}'")

        # --- 4. Regla: load_playlist NO reproduce ---
        print("\n--- 4. Probando Regla: load_playlist NO reproduce ---")
        render.load_playlist(p1.id)
        status, track = print_status(render, "load_playlist")
        
        if status.state != Spotifice.PlaybackState.STOPPED:
             print(f"  [ERROR] Debería estar STOPPED, está {status.state}")
        else:
             print("  [ÉXITO] Carga correcta sin autostart.")

        # --- 5. Play / Pause / Resume (AHORA AUTENTICADO) ---
        print("\n--- 5. Probando Play/Pause/Resume (Streaming Autenticado) ---")
        print("Iniciando reproducción (play)...")
        render.play()
        sleep(3)
        st, _ = print_status(render, "play")
        if st.state != Spotifice.PlaybackState.PLAYING:
            print("  [ERROR] No está reproduciendo. ¿Fallo de auth o gstreamer?")
        else:
            print("  [ÉXITO] Reproduciendo audio autenticado.")

        print("Pausando...")
        render.pause()
        sleep(2)
        print_status(render, "pause")

        print("Reanudando...")
        render.play()
        sleep(2)
        print_status(render, "resume")

        # --- 6. Next / Previous / Repeat ---
        print("\n--- 6. Probando Next / Previous / Repeat ---")
        render.next()
        sleep(2)
        print_status(render, "next 1")
        
        render.next()
        sleep(2)
        print_status(render, "next 2")

        render.previous()
        sleep(2)
        print_status(render, "previous")
        
        print("Activando repetición...")
        render.set_repeat(True)
        print_status(render, "repeat on")
        render.set_repeat(False)

        # --- 7. Reglas de Comportamiento (Estados) ---
        print("\n--- 7. Probando Reglas de Estado (Hito 1.4) ---")

        print("\n[Regla A] Mantener estado PAUSED al cambiar pista:")
        # Situación: Estamos en PLAYING. Pausamos.
        render.pause()
        print_status(render, "Pre-Next (Paused)")
        
        print("Ejecutando next()...")
        render.next()
        st, tr = print_status(render, "Post-Next")
        
        if st.state == Spotifice.PlaybackState.PAUSED:
            print("  [ÉXITO] Se mantuvo en PAUSED tras next().")
        else:
            print(f"  [ERROR] El estado cambió a {st.state} (se esperaba PAUSED)")
            
        # Volvemos a play para la siguiente prueba
        render.play() 
        sleep(1)

        print("\n[Regla B] Mantener estado STOPPED al cambiar pista:")
        render.stop()
        print_status(render, "Pre-Prev (Stopped)")
        
        print("Ejecutando previous()...")
        render.previous()
        st, tr = print_status(render, "Post-Prev")
        
        if st.state == Spotifice.PlaybackState.STOPPED:
             print("  [ÉXITO] Se mantuvo en STOPPED tras previous().")
        else:
             print(f"  [ERROR] El estado cambió a {st.state}")

        # --- 8. Stop reinicia pista ---
        print("\n--- 8. Probando: Stop reinicia pista ---")
        print("Reproduciendo...")
        render.play()
        sleep(3)
        print("Stop...")
        render.stop() # Esto debe reiniciar el cursor de gstreamer a 0
        sleep(1)
        print("Play de nuevo (debe empezar desde 0)...")
        render.play()
        sleep(3)
        print_status(render, "Re-Play")

        # --- 9. Escenario Histórico ---
        print("\n--- 9. Probando Histórico ---")
        render.stop()
        render.load_playlist(p1.id) # Historial reiniciado [T1]
        render.next()               # [T1, T2]
        
        # Cargamos pista suelta (de otra playlist o la misma)
        t_id_suelta = p2.track_ids[0]
        print(f"Cargando pista individual: {t_id_suelta}")
        render.load_track(t_id_suelta) # [T1, T2, T3]
        
        print("Ejecutando previous() (Debería volver a T2)...")
        render.previous()
        st, tr = print_status(render, "Post-Previous")
        
        expected = p1.track_ids[1] # T2 es la segunda de la p1
        if tr.id == expected:
            print(f"  [ÉXITO] Volvió a la pista correcta: {tr.title}")
        else:
            print(f"  [ERROR] Pista incorrecta. Esperada: {expected}, Actual: {tr.id}")

        # --- 10. Excepciones ---
        print("\n--- 10. Probando Excepciones ---")
        render.play()
        sleep(1)
        render.pause() # Estado PAUSED
        test_exception(render.pause, Spotifice.PlayerError, "Pausar en PAUSED")
        
        render.stop() # Estado STOPPED
        test_exception(render.pause, Spotifice.PlayerError, "Pausar en STOPPED")

        print("\n--- FIN DE PRUEBAS ---")
        render.unbind_media_server() # Cierra sesión

    except Exception as e:
        print(f"\n❌ Error inesperado durante las pruebas: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    with Ice.initialize(sys.argv[1]) as ic:
        main(ic)