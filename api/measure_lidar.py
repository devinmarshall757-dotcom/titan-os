from http.server import BaseHTTPRequestHandler
import json
import math
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from measure_pipeline import measure_roof
from _rate_limit import apply_rate_limit

MAX_BODY_BYTES = 32_768      # 32 KB
MAX_PARCEL_COORDS_TOTAL = 2000
MAX_RINGS = 20
MAX_POLYGONS = 5
MAX_PARCEL_DIAGONAL_M = 500.0
MAX_CENTROID_DISTANCE_M = 250.0

# CORS: comma-separated origins in env var; default to production domain only.
_ALLOWED_ORIGINS = set(
    o.strip()
    for o in os.environ.get(
        'CORS_ALLOWED_ORIGINS',
        'https://titanconsultingcontracting.com,https://titan-pitch-pi.vercel.app'
    ).split(',')
    if o.strip()
)


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6_371_000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _validate_position(pos, path: str) -> None:
    """Validate a single [lon, lat] coordinate pair."""
    if not isinstance(pos, list) or len(pos) < 2:
        raise ValueError(f"Invalid {path}: must be [lon, lat]")
    lon_v, lat_v = pos[0], pos[1]
    # isinstance(True, int) is True — reject booleans explicitly
    if isinstance(lon_v, bool) or isinstance(lat_v, bool):
        raise ValueError(f"Invalid {path}: coordinates must not be booleans")
    if not isinstance(lon_v, (int, float)) or not isinstance(lat_v, (int, float)):
        raise ValueError(f"Invalid {path}: coordinates must be numbers")
    if not math.isfinite(lon_v) or not math.isfinite(lat_v):
        raise ValueError(f"Invalid {path}: coordinates must be finite")
    if not (-180.0 <= lon_v <= 180.0):
        raise ValueError(f"Invalid {path}: longitude {lon_v} out of range [-180, 180]")
    if not (-90.0 <= lat_v <= 90.0):
        raise ValueError(f"Invalid {path}: latitude {lat_v} out of range [-90, 90]")


def _validate_ring(ring, path: str) -> int:
    """Validate a ring, return its coordinate count."""
    if not isinstance(ring, list):
        raise ValueError(f"Invalid {path}: must be a list of positions")
    if len(ring) < 4:
        raise ValueError(f"Invalid {path}: must have >= 4 positions (3 unique + closing)")
    if ring[0] != ring[-1]:
        raise ValueError(f"Invalid {path}: ring must be closed (first position must equal last)")
    for i, pos in enumerate(ring):
        _validate_position(pos, f"{path}[{i}]")
    return len(ring)


def _validate_parcel_geojson(geojson, request_lat: float = None, request_lon: float = None) -> None:
    """Validate parcel_geojson is null or a well-formed Polygon/MultiPolygon.
    Raises ValueError with a stable public message on any failure.
    Optionally checks centroid distance and diagonal against the request coordinates."""
    if geojson is None:
        return
    if not isinstance(geojson, dict):
        raise ValueError("parcel_geojson must be null or a GeoJSON object")
    gtype = geojson.get("type")
    if gtype not in ("Polygon", "MultiPolygon"):
        raise ValueError("parcel_geojson must be a Polygon or MultiPolygon")
    coords = geojson.get("coordinates")
    if not isinstance(coords, list) or not coords:
        raise ValueError("parcel_geojson missing or empty coordinates")

    if gtype == "Polygon":
        polygons = [coords]
    else:
        polygons = coords

    if len(polygons) > MAX_POLYGONS:
        raise ValueError(f"parcel_geojson exceeds {MAX_POLYGONS} polygon limit")

    total_coords = 0
    ring_count = 0
    all_lons, all_lats = [], []

    for pi, poly in enumerate(polygons):
        if not isinstance(poly, list) or not poly:
            raise ValueError(f"parcel_geojson polygon[{pi}] malformed")
        if len(poly) > MAX_RINGS:
            raise ValueError(f"parcel_geojson polygon[{pi}] exceeds {MAX_RINGS} ring limit")
        for ri, ring in enumerate(poly):
            ring_count += 1
            total_coords += _validate_ring(ring, f"polygon[{pi}].ring[{ri}]")
            if total_coords > MAX_PARCEL_COORDS_TOTAL:
                raise ValueError(f"parcel_geojson exceeds {MAX_PARCEL_COORDS_TOTAL} total coordinate limit")
            if pi == 0 and ri == 0:
                for pos in ring:
                    all_lons.append(pos[0])
                    all_lats.append(pos[1])

    if all_lons and request_lat is not None and request_lon is not None:
        min_lon, max_lon = min(all_lons), max(all_lons)
        min_lat, max_lat = min(all_lats), max(all_lats)
        clon = (min_lon + max_lon) / 2
        clat = (min_lat + max_lat) / 2

        diagonal = _haversine_m(min_lat, min_lon, max_lat, max_lon)
        if diagonal > MAX_PARCEL_DIAGONAL_M:
            raise ValueError(
                f"parcel_geojson diagonal ({diagonal:.0f}m) exceeds {MAX_PARCEL_DIAGONAL_M:.0f}m residential limit"
            )

        dist = _haversine_m(request_lat, request_lon, clat, clon)
        if dist > MAX_CENTROID_DISTANCE_M:
            raise ValueError(
                f"parcel_geojson centroid is {dist:.0f}m from request coordinates "
                f"(limit {MAX_CENTROID_DISTANCE_M:.0f}m)"
            )


def _cors_origin(request_origin: str) -> str:
    """Return the allowed origin header value, or empty string if not allowed."""
    return request_origin if request_origin in _ALLOWED_ORIGINS else ''


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            if apply_rate_limit(self, 'measure_lidar'):
                return

            content_length_header = self.headers.get('Content-Length')
            if content_length_header is None:
                self._respond(411, {'error': 'Content-Length required'})
                return
            try:
                length = int(content_length_header)
            except (ValueError, TypeError):
                self._respond(400, {'error': 'Invalid Content-Length'})
                return
            if length <= 0:
                self._respond(400, {'error': 'Content-Length must be positive'})
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

            if not isinstance(body, dict):
                self._respond(400, {'error': 'Request body must be a JSON object'})
                return

            lat = body.get('lat')
            lon = body.get('lon')
            parcel_geojson = body.get('parcel_geojson')

            if lat is None or lon is None:
                self._respond(400, {'error': 'lat and lon required'})
                return

            if isinstance(lat, bool) or isinstance(lon, bool):
                self._respond(400, {'error': 'lat and lon must be numbers'})
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
                _validate_parcel_geojson(parcel_geojson, request_lat=lat, request_lon=lon)
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
        origin = self.headers.get('Origin', '')
        allowed = _cors_origin(origin)
        self.send_response(200)
        self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        if allowed:
            self.send_header('Access-Control-Allow-Origin', allowed)
            self.send_header('Vary', 'Origin')
        self.send_header('Content-Length', '0')
        self.end_headers()

    def _respond(self, status, data):
        body = json.dumps(data).encode()
        origin = self.headers.get('Origin', '')
        allowed = _cors_origin(origin)
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', len(body))
        if allowed:
            self.send_header('Access-Control-Allow-Origin', allowed)
            self.send_header('Vary', 'Origin')
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass
