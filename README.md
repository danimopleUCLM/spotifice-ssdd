# 🎧 Spotifice

Sistema distribuido de streaming de audio construido sobre el middleware **ZeroC Ice**, desarrollado como práctica de la asignatura **Sistemas Distribuidos** (Grado en Ingeniería Informática — UCLM-ESI).

**Autor de la implementación:** Daniel Moreno Pleite

---

## ⚠️ Nota de autoría

Este repositorio parte de una **plantilla base proporcionada por el equipo docente** de la asignatura a través de GitHub Classroom (estructura de carpetas, definición de interfaces Ice, ficheros de configuración de ejemplo, tests automáticos de evaluación, playlists de ejemplo y el reproductor local `gst_player.py`).

Además, **`media_server.py` y `media_render.py` partían ya de un esqueleto base proporcionado por la profesora** (estructura de clases, `main()`, carga inicial de recursos, etc.), y **mi trabajo ha consistido en implementar sobre esa base las funcionalidades que pedía el enunciado de cada hito** (playlists, nuevas operaciones de reproducción, autenticación, sesiones seguras, descubrimiento y búsqueda). `media_control.py` y `media_directory.py` los he escrito íntegramente yo, sin esqueleto previo. La sección [Estructura del proyecto](#-estructura-del-proyecto) detalla qué partes corresponden a la plantilla base y cuáles he implementado o ampliado yo.

## 📖 Descripción general

Spotifice es una aplicación distribuida de streaming de audio que simula, con fines didácticos, el funcionamiento de un servicio tipo Spotify. Su objetivo es poner en práctica los conceptos de sistemas distribuidos: invocación remota de objetos, mensajería publicación-suscripción, autenticación y descubrimiento dinámico de servicios, en lugar de centrarse en la reproducción de audio en sí.

El sistema sigue un modelo de **streaming controlado por el receptor** (*pull-based*): es el reproductor (el cliente) quien decide cuándo y cuánto audio solicitar al servidor en función del estado de su buffer, en lugar de que el servidor empuje datos sin control. Esto evita saturar la red y reduce los cortes de reproducción frente a un modelo en el que el servidor fuerza la tasa de envío.

La aplicación está formada por **cuatro componentes independientes** que se comunican entre sí mediante objetos remotos definidos con Slice (el lenguaje de definición de interfaces de Ice):

```
                 ┌─────────────────┐
        mp3 ──▶  │   MediaServer    │
                 │ (media_server.py)│
                 └───┬─────────┬────┘
                     │         │  SecureStreamManager
       MusicLibrary  │         │  (streaming autenticado)
       Playlist/Auth │         ▼
       MediaFinder   │   ┌──────────────────┐
                     │   │   MediaRender    │──▶ 🔊 player local
                     │   │ (media_render.py)│    (gst_player.py)
                     │   └────────┬─────────┘
                     │            │
                     ▼            ▼
              ┌──────────────────────────┐
              │       MediaControl       │  (cliente de pruebas)
              │    (media_control.py)    │
              └──────────────────────────┘

   IceStorm (pub/sub): DiscoveryTopic + FinderTopic
              │
              ▼
     ┌──────────────────────┐
     │    MediaDirectory     │  (registro de servidores/renders activos)
     │ (media_directory.py)  │
     └──────────────────────┘
```

- **MediaServer**: almacena las pistas de audio (`.mp3`) y las playlists, sirve los fragmentos de audio a quien esté autenticado y responde a búsquedas de contenido.
- **MediaRender**: consume el audio en streaming y lo reproduce localmente; se vincula a un `MediaServer` y expone control de reproducción (play/pause/stop/next/previous/repeat).
- **MediaControl**: cliente de línea de comandos que conecta los dos componentes anteriores y sirve como banco de pruebas end-to-end de todo el sistema.
- **MediaDirectory**: servicio de registro que mantiene, en tiempo real, qué `MediaServer` y `MediaRender` están activos en la red, gracias a anuncios recibidos vía IceStorm.

## 🧩 Contrato de interfaces (`spotifice_v3.ice`)

Todas las interfaces remotas están definidas en el fichero Slice `spotifice_v3.ice` **proporcionado por el equipo docente** (ampliado en sucesivas versiones a medida que se plantean nuevos hitos). Resumen de las interfaces relevantes:

| Interfaz | Implementada por | Operaciones principales |
|---|---|---|
| `MusicLibrary` | `MediaServer` | `get_all_tracks()`, `get_track_info()` |
| `PlaylistManager` | `MediaServer` | `get_all_playlists()`, `get_playlist()` |
| `AuthManager` | `MediaServer` | `authenticate()` → devuelve una sesión `SecureStreamManager` |
| `MediaFinder` / `MediaFinderListener` | `MediaServer` / `MediaControl` | `find_track()`, `find_playlist()`, `track_found()`, `playlist_found()` |
| `Session` / `SecureStreamManager` | Objeto de sesión (creado por `authenticate()`) | `get_user_info()`, `open_stream()`, `close_stream()`, `get_audio_chunk()`, `close()` |
| `RenderConnectivity` | `MediaRender` | `bind_media_server()`, `unbind_media_server()` |
| `ContentManager` | `MediaRender` | `get_current_track()`, `load_track()`, `load_playlist()` |
| `PlaybackController` | `MediaRender` | `play()`, `pause()`, `stop()`, `next()`, `previous()`, `set_repeat()`, `get_status()` |
| `AnnounceListener` / `Directory` | `MediaDirectory` | `server_up()`, `server_down()`, `get_media_servers()`, `get_media_renders()` |

## 🎯 Hitos implementados

El desarrollo se organiza en hitos incrementales. **Todo el código Python de los cuatro componentes (`media_server.py`, `media_render.py`, `media_control.py`, `media_directory.py`) es implementación propia**; a continuación se detalla qué aporta cada hito.

### Hito 0 — Identificación
Fichero `STUDENT` con los datos del alumno, requisito administrativo para la evaluación automática.

### Hito 1 — Playlists y control de reproducción
- Carga en memoria de las playlists (`playlists/*.playlist`, formato JSON) al arrancar el `MediaServer`, ignorando pistas listadas que no estén disponibles.
- Implementación de `get_all_playlists()` y `get_playlist()`.
- `load_playlist()` en `MediaRender`: carga la playlist y su primera pista sin iniciar la reproducción.
- Extensión del reproductor con `pause()`, `get_status()`, `next()`, `previous()` y `set_repeat()`, incluyendo:
  - Histórico de reproducción para `previous()` (se reinicia al cambiar de servidor o cargar playlist).
  - Comportamiento de `next()`/`previous()` respecto al modo repetición.
  - `stop()` conserva la pista actual para que `play()` la reanude desde el principio.

### Hito 2 — Autenticación y sesiones seguras
- Sustitución del antiguo `StreamManager` (sin control de acceso) por `SecureStreamManager`, ligado a una `Session` por cliente.
- `authenticate()` actúa como una **factoría de objetos remotos**: valida usuario/contraseña contra `users.json` (hash MD5 + salt, verificación con `hashlib` y `secrets.compare_digest` para evitar *timing attacks*) y devuelve un proxy `SecureStreamManager` específico para esa sesión.
- Control de sesiones activas por identidad de `MediaRender`: impide que dos usuarios distintos compartan el mismo render simultáneamente, y permite reconexión transparente si el mismo usuario vuelve a autenticarse.
- `MediaRender.bind_media_server()` ahora recibe también el proxy de sesión, y usa ese canal autenticado (`stream_manager.get_audio_chunk()`) para pedir los fragmentos de audio en lugar de hablar directamente con el `MediaServer`.

### Hito 3 — Descubrimiento y búsqueda distribuida
Este hito introduce mensajería publicación-suscripción vía **IceStorm** y un nuevo componente:

- **`media_directory.py` es un programa completamente nuevo** (no forma parte de la plantilla base): implementa `MediaDirectory`, suscrita al canal `DiscoveryTopic`, manteniendo en memoria (con bloqueo de concurrencia) qué servidores y renders están vivos y desde cuándo.
- `MediaServer` y `MediaRender` se anuncian periódicamente en `DiscoveryTopic` mediante un hilo (`announce_loop`) que publica su proxy cada `Discovery.AnnounceIntervalSecs` segundos, con identidad configurable o un UUID por defecto.
- Servicio de búsqueda de contenido sobre el canal `FinderTopic`: `MediaControl` publica una búsqueda (`find_track`/`find_playlist`) y cada `MediaServer` suscrito responde de forma asíncrona —sólo si tiene el contenido— invocando `track_found()`/`playlist_found()` sobre un listener temporal creado por el cliente.
- Esto permite que **varios `MediaServer` coexistan** y respondan a la misma consulta sin que el cliente necesite conocerlos de antemano ni depender de configuración estática.

## ⚙️ Tecnologías y requisitos

- **Python 3.10+**
- **ZeroC Ice 3.7** (bindings de Python) — middleware de invocación remota de objetos
- **IceStorm / IceBox** — servicio de mensajería publicación-suscripción usado en el Hito 3
- **GStreamer**, a través del reproductor `gst_player.py` (proporcionado)
- `pytest` para los tests automáticos
- Librería estándar: `hashlib`, `secrets`, `uuid`, `threading`, `json`, `pathlib`

Las dependencias exactas se listan en el fichero `DEPENDS` del proyecto.

## 📂 Estructura del proyecto

| Fichero / carpeta | Origen | Descripción |
|---|---|---|
| `spotifice_v3.ice` | 🏫 Plantilla base | Definición de las interfaces remotas (contrato Ice) |
| `media_server.py` | 🏫 Esqueleto + 👤 Ampliado por mí | Lógica de `MediaServer`: catálogo, playlists, autenticación, streaming y búsqueda |
| `media_render.py` | 🏫 Esqueleto + 👤 Ampliado por mí | Lógica de `MediaRender`: reproducción, control, anuncio de presencia |
| `media_control.py` | 👤 Implementación propia (sin esqueleto previo) | Cliente de pruebas: descubrimiento, búsqueda, autenticación y reproducción end-to-end |
| `media_directory.py` | 👤 Implementación propia (sin esqueleto previo, Hito 3) | Registro de servidores y renders activos vía IceStorm |
| `gst_player.py` | 🏫 Plantilla base | Reproductor local de `.mp3` sobre GStreamer |
| `server.config` / `render.config` / `control.config` / `directory.config` | 🏫 Base, ampliados por mí | Propiedades de configuración de cada componente (endpoints, IceStorm, identidades) |
| `icebox.config` | 🏫 / 👤 | Configuración del servicio IceStorm ejecutado sobre IceBox (necesario para el Hito 3) |
| `users.json` | 🏫 Plantilla base | Credenciales de prueba (usuario/contraseña con hash + salt) |
| `playlists/` | 🏫 Plantilla base | Playlists de ejemplo (banda sonora de *Portal 2*) |
| `test/` | 🏫 Plantilla base | Tests automáticos usados en la evaluación |
| `Makefile` | 🏫 Plantilla base | Tareas: descarga de audio, tests, arranque rápido |
| `run.sh` | 🏫 Plantilla base | Script `tmux` para lanzar varios componentes a la vez |
| `STUDENT` | 👤 Requerido | Identificación del alumno para la evaluación automática |

## 🚀 Puesta en marcha

### 1. Instalar dependencias
Revisa el fichero `DEPENDS` para la lista completa (Ice, GStreamer, etc.).

### 2. Descargar las pistas de audio de ejemplo
```bash
make media
```
Descarga y descomprime la banda sonora de *Portal 2* en el directorio `media/`.

### 3. Arrancar el servicio IceStorm (necesario a partir del Hito 3)
```bash
icebox --Ice.Config=icebox.config
```

### 4. Arrancar el directorio de servicios
```bash
./media_directory.py directory.config
```

### 5. Arrancar uno o varios servidores de medios
```bash
./media_server.py server.config
```

### 6. Arrancar un reproductor (render)
```bash
./media_render.py render.config
```

### 7. Ejecutar el cliente de pruebas
```bash
./media_control.py control.config
```

Alternativamente, el script `run.sh` levanta servidor, render y control en una sesión `tmux` con un solo comando:
```bash
./run.sh
```

### Ejecutar los tests
```bash
make test
```

## 🔐 Usuarios de prueba

El fichero `users.json` incluye credenciales de ejemplo para probar la autenticación:

| Usuario | Contraseña |
|---|---|
| `user` | `secret` |
| `jdoe` | *(ver `users.json`)* |

## 📎 Créditos

- **Plantilla base, interfaces Ice y enunciado de la práctica**: profesorado de la asignatura Sistemas Distribuidos (UCLM-ESI).
- **Implementación de los Hitos 1, 2 y 3**: Daniel Moreno Pleite.

> Este repositorio se comparte con fines de portfolio personal. Si estás cursando la misma asignatura, recuerda que la normativa académica de la UCLM prohíbe la entrega de código copiado de otros compañeros.
