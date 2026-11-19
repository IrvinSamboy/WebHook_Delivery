"""Receptor de webhooks para desarrollo: imprime lo que llega y valida la firma.

    make receiver secret=whsec_...
    make receiver secret=whsec_... status=500   # simula un receptor caído

Responde 204 si la firma es válida y 401 si no lo es. Con RECEIVER_STATUS
responde siempre ese código: sirve para ver los reintentos en acción.
"""

import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from relay.domain.signing import verify

SECRET = os.environ.get("WEBHOOK_SECRET", "")
FORCED_STATUS = int(os.environ.get("RECEIVER_STATUS") or 0)
PORT = 9000


class Receiver(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        body = self.rfile.read(int(self.headers.get("content-length", 0)))
        webhook_id = self.headers.get("webhook-id", "")
        try:
            valid = verify(
                SECRET,
                webhook_id,
                self.headers.get("webhook-timestamp", ""),
                self.headers.get("webhook-signature", ""),
                body,
                now=int(time.time()),
            )
        except ValueError:  # Secreto mal copiado: no es base64 válido.
            valid = False
        status = FORCED_STATUS or (204 if valid else 401)
        mark = "✅ firma válida  " if valid else "❌ firma inválida"
        print(
            f"{time.strftime('%H:%M:%S')} {mark} → {status} "
            f"webhook-id={webhook_id} {body.decode(errors='replace')}",
            flush=True,
        )
        self.send_response(status)
        self.end_headers()

    def log_message(self, *args: object) -> None:
        pass  # Sin la línea de log por defecto: ya imprimimos lo importante.


if __name__ == "__main__":
    if not SECRET:
        print("Aviso: falta WEBHOOK_SECRET; todas las firmas serán inválidas.", flush=True)
    if FORCED_STATUS:
        print(f"Responderá siempre {FORCED_STATUS}.", flush=True)
    print(f"Receptor escuchando en :{PORT}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Receiver).serve_forever()
