from http.server import BaseHTTPRequestHandler
import json
import math
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from measure_pipeline import measure_roof

MAX_BODY_BYTES = 32_768  # 32 KB — parcel GeoJSON is never legitimately larger
MAX_PARCEL_COORDS = 500   # per ring


def _validate_parcel_geojson(geojson):
    """Return True if geojson is a null or a plausible Polygon/MultiPolygon object.
    Raises ValueError with a safe public message on failure."""
    if geojson is None:
        return True
    if not isinstance(geojson, dict):
        raise ValueError("parcel_geojson must be null or a GeoJSON object")
    gtype = geojson.get("type")
    if gtype not in ("Polygon", "MultiPolygon"):
        raise ValueError("parcel_geojson must be a Polygon or MultiPolygon")
    coords = geojson.get("coordinates")
    if not isinstance(coords, list) or not coords:
        raise ValueError("parcel_geojson missing coordinates")
    # For Polygon: coords is [[ring, ...]]
    # For MultiPolygon: coords is [[[ring, ...], ...], ...]
    rings = coords if gtype == "Polygon" else [ring for poly in coords for ring in poly]
    for ring in rings:
        if not isinstance(ring, list):
            raise ValueError("parcel_geojson coordinates malformed")
        if len(ring) > MAX_PARCEL_COORDS:
            raise ValueError(f"parcel_geojson ring exceeds {MAX_PARCEL_COORDS} coordinate limit")
    return True


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            content_length_header = self.headers.get('Content-Length')
            if content_length_header is None:
                self._respond(411, {'error': 'Content-Length required'})
                return
            try:
                length = int(content_length_header)
            except (ValueError, TypeError):
                self._respond(400, {'error': 'Invalid Content-Length'})
                return
            if length > MAX_BODY_BYTES:
                self._respond(413, {'error': 'Request body too large'})
                return

            raw = self.rfile.read(length)
            try:
                body = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                self._respond(400, {'error': 'Invalid JSON'})
                return

            lat = body.get('lat')
            lon = body.get('lon')
            parcel_geojson = body.get('parcel_geojson')

            if lat is None or lon is None:
                self._respond(400, {'error': 'lat and lon required'})
                return

            try:
                lat = float(lat)
                lon = float(lon)
            except (TypeError, ValueError):
                self._respond(400, {'error': 'lat and lon must be numbers'})
                return

            if not math.isfinite(lat) or not math.isfinite(lon):
                self._respond(400, {'error': 'lat and lon must be finite numbers'})
                return

            if not (-90.0 <= lat <= 90.0):
                self._respond(400, {'error': 'lat must be between -90 and 90'})
                return

            if not (-180.0 <= lon <= 180.0):
                self._respond(400, {'error': 'lon must be between -180 and 180'})
                return

            try:
                _validate_parcel_geojson(parcel_geojson)
            except ValueError as ve:
                self._respond(400, {'error': str(ve)})
                return

            result = measure_roof(lat, lon, parcel_geojson=parcel_geojson)
            self._respond(200, result)

        except ValueError as e:
            print(f'[measure_lidar] validation error: {e}', file=sys.stderr)
            self._respond(400, {'error': str(e)})
        except Exception as e:
            print(f'[measure_lidar] internal error: {type(e).__name__}: {e}', file=sys.stderr)
            self._respond(500, {'error': 'Measurement unavailable'})

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
