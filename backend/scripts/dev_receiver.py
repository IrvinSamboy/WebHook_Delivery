"""Receptor de webhooks para desarrollo: imprime lo que llega y valida la firma.

    make receiver secret=whsec_...

Responde 204 si la firma es válida y 401 si no lo es.
"""

import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from relay.domain.signing import verify

SECRET = os.environ.get("WEBHOOK_SECRET", "")
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
        mark = "✅ firma válida  " if valid else "❌ firma inválida"
        print(f"{mark} webhook-id={webhook_id} {body.decode(errors='replace')}", flush=True)
        self.send_response(204 if valid else 401)
        self.end_headers()

    def log_message(self, *args: object) -> None:
        pass  # Sin la línea de log por defecto: ya imprimimos lo importante.


if __name__ == "__main__":
    if not SECRET:
        print("Aviso: falta WEBHOOK_SECRET; todas las firmas serán inválidas.", flush=True)
    print(f"Receptor escuchando en :{PORT}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Receiver).serve_forever()
