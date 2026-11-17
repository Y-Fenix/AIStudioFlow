"""Remove expired private upload payloads; never execute work or send messages."""
import logging
import threading
from server.core.public_area.service import PublicArea


class PublicMaintenance:
    def __init__(self, store):
        self.store = store
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.run, name='public-cleanup', daemon=True)
        self.thread.start()

    def run(self):
        while not self.stop.is_set():
            try:
                PublicArea(self.store).cleanup()
            except Exception:
                logging.getLogger(__name__).error('Public staging cleanup failed')
            self.stop.wait(3600)

    def close(self):
        self.stop.set()
        self.thread.join(timeout=5)
