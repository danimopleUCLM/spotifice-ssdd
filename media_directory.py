#!/usr/bin/env python3
import sys
import threading
import time
import Ice
import IceStorm

# Cargamos V3
Ice.loadSlice('-I{} spotifice_v3.ice'.format(Ice.getSliceDir()))
import Spotifice

class DirectoryI(Spotifice.MediaDirectory):
    def __init__(self):
        self._lock = threading.Lock()
        self._servers = {}
        self._renders = {}

    def server_up(self, proxy, current=None):
        # El proxy llega como Object*, hay que comprobar qué es realmente
        if Spotifice.MediaServerPrx.checkedCast(proxy):
            self._update_entry(proxy, is_server=True)
        elif Spotifice.MediaRenderPrx.checkedCast(proxy):
            self._update_entry(proxy, is_server=False)
        else:
            print(f"[Directory] Ignorado anuncio de objeto desconocido: {proxy}")

    def server_down(self, proxy, current=None):
        pass

    def _update_entry(self, proxy, is_server):
        with self._lock:
            try:
                ident = proxy.ice_getIdentity()
                key = Ice.identityToString(ident)
                
                if is_server:
                    # Guardamos proxy casteado y timestamp
                    server_prx = Spotifice.MediaServerPrx.uncheckedCast(proxy)
                    self._servers[key] = (server_prx, time.time())
                    print(f"[Directory] Server UP: {key}")
                else:
                    render_prx = Spotifice.MediaRenderPrx.uncheckedCast(proxy)
                    self._renders[key] = (render_prx, time.time())
                    print(f"[Directory] Render UP: {key}")
            except Exception as e:
                print(f"Error updating entry: {e}")

    # Implementación de Directory
    def get_media_servers(self, current=None):
        with self._lock:
            return [v[0] for v in self._servers.values()]

    def get_media_renders(self, current=None):
        with self._lock:
            return [v[0] for v in self._renders.values()]

def main(ic):
    props = ic.getProperties()
    topic_mgr_str = props.getProperty("IceStorm.TopicManager.Proxy")
    topic_name = props.getPropertyWithDefault("Discovery.TopicName", "DiscoveryTopic")
    identity = props.getPropertyWithDefault("MediaDirectory.Identity", "directory")

    if not topic_mgr_str:
        print("Error: IceStorm.TopicManager.Proxy property is missing")
        return

    adapter = ic.createObjectAdapter("MediaDirectoryAdapter")
    
    # Instanciamos la clase corregida
    servant = DirectoryI()
    
    try:
        topic_mgr = IceStorm.TopicManagerPrx.checkedCast(ic.stringToProxy(topic_mgr_str))
        if not topic_mgr:
            raise RuntimeError("Invalid TopicManager proxy")

        try:
            topic = topic_mgr.retrieve(topic_name)
        except IceStorm.NoSuchTopic:
            topic = topic_mgr.create(topic_name)

        subscriber = adapter.add(servant, ic.stringToIdentity(identity))
        
        qos = {}
        topic.subscribeAndGetPublisher(qos, subscriber)
        print(f"MediaDirectory activo y suscrito a {topic_name}")

    except Exception as e:
        print(f"Error conectando a IceStorm: {e}")
        return

    adapter.activate()
    ic.waitForShutdown()
    
    topic.unsubscribe(subscriber)

if __name__ == "__main__":
    # Si no hay argumentos, le pasamos el config por defecto nosotros
    config = sys.argv[1] if len(sys.argv) > 1 else "directory.config"
    with Ice.initialize(["--Ice.Config=" + config]) as ic:
        main(ic)