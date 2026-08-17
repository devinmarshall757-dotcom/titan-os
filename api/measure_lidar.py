from http.server import BaseHTTPRequestHandler
import json
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from measure_pipeline import measure_roof


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            length = int(self.headers.get('Content-Length', 0))
            body = json.loads(self.rfile.read(length))
            lat = body.get('lat')
            lon = body.get('lon')
            parcel_geojson = body.get('parcel_geojson')

            if lat is None or lon is None:
                self._respond(400, {'error': 'lat and lon required'})
                return

            result = measure_roof(float(lat), float(lon), parcel_geojson=parcel_geojson)
            self._respond(200, result)

        except ValueError as e:
            self._respond(400, {'error': str(e)})
        except Exception as e:
            self._respond(500, {'error': str(e)})

    def do_OPTIONS(self):
        self._respond(200, {})

    def _respond(self, status, data):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', len(body))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass
