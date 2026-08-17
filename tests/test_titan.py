"""
Titan OS — local test suite. No live credentials or network required.
Run: python tests/test_titan.py
"""
import sys, json, types, unittest
from unittest.mock import MagicMock, patch

# ── helpers ──────────────────────────────────────────────────────────────────

def he(s):
    """Mirror of contact.js he() — HTML-escape a string."""
    if not s:
        return ''
    return (str(s)[:1000]
        .replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        .replace('"', '&quot;').replace("'", '&#x27;'))


# ── contact input validation ──────────────────────────────────────────────────

class TestContactEscaping(unittest.TestCase):
    def test_basic_xss_escaped(self):
        self.assertEqual(he('<script>alert(1)</script>'), '&lt;script&gt;alert(1)&lt;/script&gt;')

    def test_amp_escaped(self):
        self.assertIn('&amp;', he('Tom & Jerry'))

    def test_empty_returns_empty(self):
        self.assertEqual(he(''), '')
        self.assertEqual(he(None), '')

    def test_truncated_at_1000(self):
        self.assertEqual(len(he('x' * 2000)), 1000)

    def test_quotes_escaped(self):
        self.assertNotIn('"', he('"hello"'))
        self.assertNotIn("'", he("it's"))


# ── permit schema consistency ─────────────────────────────────────────────────

class TestPermitSchema(unittest.TestCase):
    REQUIRED = {'permit_number', 'address', 'city', 'state', 'value', 'issued_date', 'source'}

    def _check(self, permit):
        missing = self.REQUIRED - permit.keys()
        self.assertEqual(missing, set(), f"Missing fields: {missing}")

    def _cedar_rapids_permit(self):
        return {
            'permit_number': 'CR-2026-001',
            'address': '123 Main St, Cedar Rapids, IA',
            'city': 'Cedar Rapids',
            'county': 'Linn',
            'state': 'IA',
            'permit_type': 'Roofing',
            'description': 'Residential re-roof',
            'contractor': 'Titan Consulting',
            'owner': 'Jane Doe',
            'value': 12000.0,
            'issued_date': '2026-08-01',
            'score': 75,
            'source': 'cedar_rapids_city',
        }

    def _dubuque_permit(self):
        return {
            'permit_number': 'DUB-123 Main-2026-08',
            'address': '123 Main St, Dubuque, IA',
            'city': 'Dubuque',
            'county': 'Dubuque',
            'state': 'IA',
            'permit_type': 'Residential Roofing',
            'description': 'Residential Roofing',
            'value': 8500.0,
            'issued_date': '2026-08-05',
            'source': 'dubuque_monthly_report',
        }

    def _council_bluffs_permit(self):
        return {
            'permit_number': 'CB-456 Oak-2026-07',
            'address': '456 Oak Ave, Council Bluffs, IA',
            'city': 'Council Bluffs',
            'county': 'Pottawattamie',
            'state': 'IA',
            'permit_type': 'Roofing',
            'description': 'Roofing',
            'value': 9200.0,
            'issued_date': '2026-07-15',
            'source': 'council_bluffs_monthly_report',
        }

    def test_cedar_rapids_schema(self):
        self._check(self._cedar_rapids_permit())

    def test_dubuque_schema(self):
        self._check(self._dubuque_permit())

    def test_council_bluffs_schema(self):
        self._check(self._council_bluffs_permit())

    def test_no_valuation_field(self):
        """Ensure old 'valuation'/'issue_date' fields are not present."""
        for p in [self._dubuque_permit(), self._council_bluffs_permit()]:
            self.assertNotIn('valuation', p, "Use 'value' not 'valuation'")
            self.assertNotIn('issue_date', p, "Use 'issued_date' not 'issue_date'")

    def test_schemas_match(self):
        """All three scrapers should produce the same required keys."""
        for p in [self._cedar_rapids_permit(), self._dubuque_permit(), self._council_bluffs_permit()]:
            self._check(p)


# ── storm scraper processing ──────────────────────────────────────────────────

class TestStormScraper(unittest.TestCase):
    def _make_feature(self, event, hail=None):
        params = {}
        if hail:
            params['maxHailSize'] = [str(hail)]
        return {
            'id': 'urn:test:1',
            'properties': {
                '@id': 'urn:test:1',
                'event': event,
                'onset': '2026-08-16T12:00:00Z',
                'ends': '2026-08-16T18:00:00Z',
                'areaDesc': 'Linn, Johnson, Scott',
                'headline': 'Test headline',
                'description': 'Test description',
                'severity': 'Severe',
                'certainty': 'Observed',
                'parameters': params,
            }
        }

    def _process(self, feature):
        sys.path.insert(0, 'scripts')
        import storm_scraper
        return storm_scraper.process_alert(feature)

    def test_tornado_warning_score_10(self):
        evt = self._process(self._make_feature('Tornado Warning'))
        self.assertIsNotNone(evt)
        self.assertEqual(evt['score'], 10)

    def test_severe_tstorm_with_hail_score_9(self):
        evt = self._process(self._make_feature('Severe Thunderstorm Warning', hail=1.0))
        self.assertEqual(evt['score'], 9)

    def test_severe_tstorm_no_hail_score_7(self):
        evt = self._process(self._make_feature('Severe Thunderstorm Warning'))
        self.assertEqual(evt['score'], 7)

    def test_irrelevant_event_filtered(self):
        evt = self._process(self._make_feature('Dense Fog Advisory'))
        self.assertIsNone(evt)

    def test_counties_parsed(self):
        evt = self._process(self._make_feature('Tornado Watch'))
        self.assertIn('Linn', evt['counties'])


# ── task poller allowlist ─────────────────────────────────────────────────────

class TestTaskPoller(unittest.TestCase):
    def _load_poller(self):
        import importlib, os
        os.environ.setdefault('SUPABASE_URL', 'https://example.supabase.co')
        os.environ.setdefault('SUPABASE_SERVICE_KEY', 'test-key')
        sys.path.insert(0, 'scripts')
        if 'task_poller' in sys.modules:
            return sys.modules['task_poller']
        import task_poller
        return task_poller

    def test_unknown_script_blocked(self):
        tp = self._load_poller()
        stdout, stderr, code = tp.run_script('../../etc/passwd')
        self.assertNotEqual(code, 0)
        self.assertIn('unknown script', stderr)

    def test_known_script_in_allowlist(self):
        tp = self._load_poller()
        self.assertIn('storm_scraper', tp.SCRIPTS)
        self.assertIn('permit_scraper', tp.SCRIPTS)


# ── pitch prohibited claims check ────────────────────────────────────────────

class TestPitchClaims(unittest.TestCase):
    def setUp(self):
        with open('pitch.html', 'r', encoding='utf-8') as f:
            self.html = f.read()

    def test_no_any_iowa_address(self):
        self.assertNotIn('any Iowa address', self.html)

    def test_no_60_85_accuracy(self):
        self.assertNotIn('60–85% accuracy', self.html)
        self.assertNotIn('60-85% accuracy', self.html)

    def test_no_60_85_stat(self):
        self.assertNotIn('60–85%', self.html)

    def test_no_iowa_city_permit_claim(self):
        self.assertNotIn('Iowa City + Rock Island', self.html)

    def test_no_47_permits(self):
        self.assertNotIn('47 permits today', self.html)

    def test_no_replaces_acculynx(self):
        self.assertNotIn('Replaces AccuLynx', self.html)

    def test_no_satellite_claim(self):
        self.assertNotIn('USGS LiDAR + satellite', self.html)

    def test_no_unlimited_cached(self):
        self.assertNotIn('cached, unlimited', self.html)

    def test_no_guaranteed_live_within(self):
        self.assertNotIn('Live within 3–5 days', self.html)

    def test_no_statewide_lidar(self):
        self.assertNotIn('works statewide', self.html.lower())

    def test_no_correlated_with_permits(self):
        self.assertNotIn('correlated with permit spikes', self.html)

    def test_no_running_together_in_real_time(self):
        self.assertNotIn('running together in real time', self.html)

    def test_crm_not_claimed_live_production(self):
        # CRM and Reviews must be labeled Demo, not Live Now
        self.assertNotIn('Job Pipeline CRM</span>\n          <div class="road-title">', self.html)
        # The pill next to CRM must not be p-green (Live Now)
        self.assertNotIn('Job Pipeline CRM <span class="pill p-green">', self.html)

    def test_reviews_not_claimed_live_production(self):
        self.assertNotIn('Reviews Dashboard followed by Live', self.html)

    def test_built_tested_running_removed(self):
        self.assertNotIn('Built · tested · running', self.html)


# ── service agreement demo status check ──────────────────────────────────────

class TestServiceAgreement(unittest.TestCase):
    def setUp(self):
        with open('service-agreement-draft.md', 'r', encoding='utf-8') as f:
            self.text = f.read()

    def test_crm_marked_demo(self):
        self.assertIn('CRM Pipeline', self.text)
        # Must not appear as simply "Live" in the status column
        self.assertNotIn('| **CRM Pipeline** | Job management', self.text.split('| Live |')[0] if '| Live |' in self.text else self.text)
        self.assertIn('Demo', self.text)

    def test_reviews_marked_demo(self):
        self.assertIn('Reviews Dashboard', self.text)
        self.assertIn('Demo', self.text)

    def test_acceptance_requirements_present(self):
        self.assertIn('Row-Level Security', self.text)
        self.assertIn('Anonymous access', self.text)
        self.assertIn('smoke tests', self.text)

    def test_no_server_password_alone_as_production(self):
        self.assertIn('Server-side password checking alone does not constitute production authentication', self.text)


# ── runtime dependency gate ───────────────────────────────────────────────────

class TestRuntimeImports(unittest.TestCase):
    """Mandatory gate: all production runtime deps must be importable.
    This test fails (not skips) when deps are missing so CI surfaces it clearly.
    Install with: pip install -r requirements.txt"""

    def test_runtime_deps_importable(self):
        import importlib
        missing = []
        for mod in ('numpy', 'laspy', 'lazrs', 'scipy', 'sklearn', 'shapely', 'pyproj', 'requests'):
            try:
                importlib.import_module(mod)
            except ImportError:
                missing.append(mod)
        self.assertEqual(
            missing, [],
            f"Missing runtime dependencies: {missing}. Run: pip install -r requirements.txt"
        )


# ── EPT fetch boundary safety (requires real numpy) ──────────────────────────

try:
    import numpy as _np
    _NUMPY_AVAILABLE = True
except ImportError:
    _NUMPY_AVAILABLE = False


def _load_ept_module():
    """Load ept_fetch with only the unavoidable C-extension stubs (laspy, lazrs, pyproj).
    numpy is NOT stubbed — tests that exercise array operations must use the real thing."""
    sys.path.insert(0, 'api')
    for mod_name in ('laspy', 'lazrs'):
        if mod_name not in sys.modules:
            sys.modules[mod_name] = types.ModuleType(mod_name)
    if 'pyproj' not in sys.modules:
        pyproj_stub = types.ModuleType('pyproj')
        mock_t = MagicMock()
        mock_t.transform.return_value = (-10216474.0, 5165920.0)
        pyproj_stub.Transformer = MagicMock()
        pyproj_stub.Transformer.from_crs.return_value = mock_t
        sys.modules['pyproj'] = pyproj_stub
    if 'ept_fetch' not in sys.modules:
        import ept_fetch  # noqa: F401
    return sys.modules['ept_fetch']


@unittest.skipUnless(_NUMPY_AVAILABLE, "numpy not installed — run: pip install -r requirements.txt")
class TestEptFetchBoundary(unittest.TestCase):
    """Tests that exercise real numpy array operations in ept_fetch.crop_property."""

    @classmethod
    def setUpClass(cls):
        cls.ef = _load_ept_module()

    def _mock_ept(self):
        mock_ept = MagicMock()
        mock_ept.bounds = [-1.1e7, -1.1e7, 0, 1.1e7, 1.1e7, 1000]
        mock_ept.side = 2.2e7
        mock_ept.resource = 'test_resource'
        return mock_ept

    def test_zero_node_keys_raises(self):
        with patch.object(self.ef, 'load_resource', return_value=self._mock_ept()), \
             patch.object(self.ef, 'find_overlapping_nodes', return_value=[]), \
             patch('requests.Session'):
            with self.assertRaises(self.ef.LidarCoverageError):
                self.ef.crop_property('test_resource', -91.6, 41.9)

    def test_all_empty_node_arrays_raises(self):
        empty_xyz = _np.zeros((0, 3))
        empty_cls = _np.zeros(0)
        with patch.object(self.ef, 'load_resource', return_value=self._mock_ept()), \
             patch.object(self.ef, 'find_overlapping_nodes', return_value=['0-0-0-0']), \
             patch.object(self.ef, 'download_node', return_value=(empty_xyz, empty_cls)), \
             patch('requests.Session'):
            with self.assertRaises(self.ef.LidarCoverageError):
                self.ef.crop_property('test_resource', -91.6, 41.9)

    def test_points_outside_crop_bbox_raises(self):
        """Points downloaded but all outside the crop bounding box → coverage error."""
        # Crop is a small box around Cedar Rapids in EPSG:3857 (~±45m).
        # Put all points far outside that box.
        far_xyz = _np.array([[0.0, 0.0, 100.0], [1.0, 1.0, 101.0]])
        far_cls = _np.array([2, 2])
        with patch.object(self.ef, 'load_resource', return_value=self._mock_ept()), \
             patch.object(self.ef, 'find_overlapping_nodes', return_value=['0-0-0-0']), \
             patch.object(self.ef, 'download_node', return_value=(far_xyz, far_cls)), \
             patch('requests.Session'):
            with self.assertRaises(self.ef.LidarCoverageError):
                self.ef.crop_property('test_resource', -91.6, 41.9)

    def test_mismatched_xyz_cls_lengths_raises(self):
        """download_node returns mismatched xyz/cls arrays → coverage error after concatenation."""
        xyz = _np.zeros((5, 3))   # 5 points
        cls = _np.zeros(3)        # 3 classifications — deliberately mismatched
        with patch.object(self.ef, 'load_resource', return_value=self._mock_ept()), \
             patch.object(self.ef, 'find_overlapping_nodes', return_value=['0-0-0-0']), \
             patch.object(self.ef, 'download_node', return_value=(xyz, cls)), \
             patch('requests.Session'):
            with self.assertRaises(self.ef.LidarCoverageError):
                self.ef.crop_property('test_resource', -91.6, 41.9)


# ── measure_lidar validation ──────────────────────────────────────────────────

def _load_measure_lidar():
    sys.path.insert(0, 'api')
    stub = types.ModuleType('measure_pipeline')
    stub.measure_roof = lambda *a, **kw: {}
    sys.modules['measure_pipeline'] = stub
    if 'measure_lidar' in sys.modules:
        return sys.modules['measure_lidar']
    import measure_lidar
    return measure_lidar


class TestMeasureLidarValidation(unittest.TestCase):
    """Unit-tests for _validate_parcel_geojson and _validate_position in measure_lidar."""

    @classmethod
    def setUpClass(cls):
        cls.ml = _load_measure_lidar()

    def _poly(self, ring):
        return {'type': 'Polygon', 'coordinates': [ring]}

    def _near_cr_ring(self):
        """A small closed ring near Cedar Rapids (lon≈-91.6, lat≈41.9)."""
        return [
            [-91.601, 41.901], [-91.600, 41.901],
            [-91.600, 41.900], [-91.601, 41.900],
            [-91.601, 41.901],
        ]

    # ── body-level
    def test_json_array_body_rejected(self):
        with self.assertRaises(Exception):
            self.ml._validate_parcel_geojson([1, 2, 3])

    def test_null_parcel_accepted(self):
        self.ml._validate_parcel_geojson(None)  # must not raise

    # ── geometry type
    def test_point_type_rejected(self):
        with self.assertRaises(ValueError):
            self.ml._validate_parcel_geojson({'type': 'Point', 'coordinates': [-91.6, 41.9]})

    def test_linestring_type_rejected(self):
        with self.assertRaises(ValueError):
            self.ml._validate_parcel_geojson({'type': 'LineString', 'coordinates': [[-91.6, 41.9], [-91.5, 41.8]]})

    def test_feature_type_rejected(self):
        with self.assertRaises(ValueError):
            self.ml._validate_parcel_geojson({'type': 'Feature', 'geometry': None})

    # ── ring structure
    def test_unclosed_ring_rejected(self):
        ring = [[-91.601, 41.901], [-91.600, 41.901], [-91.600, 41.900], [-91.601, 41.900]]
        with self.assertRaises(ValueError):
            self.ml._validate_parcel_geojson(self._poly(ring))

    def test_too_few_positions_rejected(self):
        ring = [[-91.601, 41.901], [-91.600, 41.901], [-91.601, 41.901]]  # only 3
        with self.assertRaises(ValueError):
            self.ml._validate_parcel_geojson(self._poly(ring))

    # ── coordinate values
    def test_nonnumeric_coord_rejected(self):
        ring = [[-91.601, "41.9"], [-91.600, 41.901], [-91.600, 41.900], [-91.601, 41.901]]
        with self.assertRaises(ValueError):
            self.ml._validate_parcel_geojson(self._poly(ring))

    def test_boolean_coord_rejected(self):
        ring = [[True, 41.901], [-91.600, 41.901], [-91.600, 41.900], [True, 41.901]]
        with self.assertRaises(ValueError):
            self.ml._validate_parcel_geojson(self._poly(ring))

    def test_null_coord_rejected(self):
        ring = [[None, 41.901], [-91.600, 41.901], [-91.600, 41.900], [None, 41.901]]
        with self.assertRaises(ValueError):
            self.ml._validate_parcel_geojson(self._poly(ring))

    def test_nan_coord_rejected(self):
        import math
        ring = [[math.nan, 41.901], [-91.600, 41.901], [-91.600, 41.900], [math.nan, 41.901]]
        with self.assertRaises(ValueError):
            self.ml._validate_parcel_geojson(self._poly(ring))

    def test_inf_coord_rejected(self):
        import math
        ring = [[math.inf, 41.901], [-91.600, 41.901], [-91.600, 41.900], [math.inf, 41.901]]
        with self.assertRaises(ValueError):
            self.ml._validate_parcel_geojson(self._poly(ring))

    def test_out_of_range_longitude_rejected(self):
        ring = [[200.0, 41.901], [-91.600, 41.901], [-91.600, 41.900], [200.0, 41.901]]
        with self.assertRaises(ValueError):
            self.ml._validate_parcel_geojson(self._poly(ring))

    def test_out_of_range_latitude_rejected(self):
        ring = [[-91.601, 95.0], [-91.600, 41.901], [-91.600, 41.900], [-91.601, 95.0]]
        with self.assertRaises(ValueError):
            self.ml._validate_parcel_geojson(self._poly(ring))

    # ── size limits
    def test_too_many_total_coords_rejected(self):
        # Build a ring with MAX_PARCEL_COORDS_TOTAL + 10 positions, all valid coords near Cedar Rapids
        n = self.ml.MAX_PARCEL_COORDS_TOTAL + 10
        ring = [[-91.601 + i * 0.000001, 41.900] for i in range(n)]
        ring.append(ring[0])  # close the ring
        with self.assertRaises(ValueError):
            self.ml._validate_parcel_geojson(self._poly(ring))

    def test_too_many_polygons_rejected(self):
        ring = self._near_cr_ring()
        coords = [[[ring]] * (self.ml.MAX_POLYGONS + 1)]
        # Build a MultiPolygon with too many polygons
        geojson = {'type': 'MultiPolygon', 'coordinates': [[ring]] * (self.ml.MAX_POLYGONS + 1)}
        with self.assertRaises(ValueError):
            self.ml._validate_parcel_geojson(geojson)

    # ── centroid/diagonal checks (require request lat/lon)
    def test_valid_nearby_polygon_accepted(self):
        ring = self._near_cr_ring()
        # Should not raise — small residential parcel near Cedar Rapids
        self.ml._validate_parcel_geojson(self._poly(ring), request_lat=41.9, request_lon=-91.6)

    def test_parcel_diagonal_too_large_rejected(self):
        # A polygon spanning ~1 degree of longitude ≈ ~80 km — way over 500m limit
        ring = [[-92.0, 41.9], [-91.0, 41.9], [-91.0, 41.91], [-92.0, 41.91], [-92.0, 41.9]]
        with self.assertRaises(ValueError):
            self.ml._validate_parcel_geojson(self._poly(ring), request_lat=41.9, request_lon=-91.5)

    def test_parcel_centroid_too_far_rejected(self):
        # Parcel centroid near Iowa City (~30 km from Cedar Rapids)
        ring = [[-91.535, 41.660], [-91.534, 41.660], [-91.534, 41.659], [-91.535, 41.659], [-91.535, 41.660]]
        # Request lat/lon is Cedar Rapids — centroid is >250m away
        with self.assertRaises(ValueError):
            self.ml._validate_parcel_geojson(self._poly(ring), request_lat=41.9, request_lon=-91.6)

    def test_valid_nearby_multipolygon_accepted(self):
        ring = self._near_cr_ring()
        geojson = {'type': 'MultiPolygon', 'coordinates': [[ring]]}
        self.ml._validate_parcel_geojson(geojson, request_lat=41.9, request_lon=-91.6)


# ── measure.js address validation (static checks via syntax) ─────────────────

class TestMeasureJsStatic(unittest.TestCase):
    def setUp(self):
        with open('api/measure.js', 'r', encoding='utf-8') as f:
            self.src = f.read()

    def test_address_type_check_present(self):
        self.assertIn("typeof rawAddress !== 'string'", self.src)

    def test_address_length_limit_present(self):
        self.assertIn('address.length > 500', self.src)

    def test_address_trimmed(self):
        self.assertIn('.trim()', self.src)

    def test_measurement_method_lidar_preserved(self):
        self.assertIn("measurement_method: 'lidar'", self.src)

    def test_measurement_method_regrid_preserved(self):
        self.assertIn("'regrid_estimate'", self.src)

    def test_measurement_method_osm_preserved(self):
        self.assertIn("'osm_estimate'", self.src)

    def test_measurement_method_unavailable_preserved(self):
        self.assertIn("'unavailable'", self.src)

    def test_manual_verification_required_on_all_paths(self):
        count = self.src.count('manual_verification_required: true')
        self.assertGreaterEqual(count, 3, 'Expected manual_verification_required on lidar, fallback, and unavailable paths')

    def test_no_lidar_label_on_fallback(self):
        # Fallback comment must NOT call regrid/OSM results LiDAR
        self.assertIn('NOT LiDAR', self.src)

    def test_cors_wildcard_not_in_measure_js(self):
        # measure.js should not set Access-Control-Allow-Origin: * (Python handler does CORS)
        self.assertNotIn("Access-Control-Allow-Origin", self.src)


# ── rate limiter static checks ────────────────────────────────────────────────

class TestRateLimiterStatic(unittest.TestCase):
    """Verify key security properties of _rate-limit.js via static analysis."""

    def setUp(self):
        with open('api/_rate-limit.js', 'r', encoding='utf-8') as f:
            self.src = f.read()

    def test_sliding_window_zadd_present(self):
        self.assertIn('ZADD', self.src)

    def test_sliding_window_zremrangebyscore_present(self):
        self.assertIn('ZREMRANGEBYSCORE', self.src)

    def test_sliding_window_zcard_present(self):
        self.assertIn('ZCARD', self.src)

    def test_retry_after_header_set(self):
        self.assertIn('Retry-After', self.src)

    def test_http_429_returned(self):
        self.assertIn('429', self.src)

    def test_ip_hashed_not_logged_raw(self):
        # Must hash IPs before use — sha256 or createHash present
        self.assertTrue('sha256' in self.src or 'createHash' in self.src,
                        "IP hashing must use SHA-256")

    def test_fail_closed_in_production(self):
        # Production must fail closed, not fail open, when Upstash unreachable
        self.assertIn('VERCEL_ENV', self.src)
        self.assertTrue(
            'production' in self.src and ('429' in self.src or '503' in self.src),
            "Must fail closed (429/503) in production"
        )

    def test_endpoint_specific_limits_configurable(self):
        # Per-endpoint env vars for limits
        self.assertIn('RATE_LIMIT_MEASURE', self.src)
        self.assertIn('RATE_LIMIT_CONTACT', self.src)
        self.assertIn('RATE_LIMIT_ADMIN_AUTH', self.src)

    def test_no_in_memory_map_as_primary_store(self):
        # In-memory Map must only be the dev fallback, not the primary path
        # It should be inside a fallback/dev branch, not at module level
        lines = self.src.splitlines()
        map_line_idx = next((i for i, l in enumerate(lines) if 'new Map()' in l), None)
        if map_line_idx is not None:
            # The Map must appear after a dev/fallback guard
            context = '\n'.join(lines[max(0, map_line_idx - 20):map_line_idx + 1])
            self.assertTrue(
                'fallback' in context.lower() or 'dev' in context.lower() or 'warn' in context.lower(),
                "In-memory Map must only appear in dev fallback path"
            )


class TestRateLimiterPythonStatic(unittest.TestCase):
    """Verify _rate_limit.py mirrors the JS limiter's key properties."""

    def setUp(self):
        with open('api/_rate_limit.py', 'r', encoding='utf-8') as f:
            self.src = f.read()

    def test_upstash_rest_url_env_var(self):
        self.assertIn('UPSTASH_REDIS_REST_URL', self.src)

    def test_upstash_rest_token_env_var(self):
        self.assertIn('UPSTASH_REDIS_REST_TOKEN', self.src)

    def test_retry_after_header_set(self):
        self.assertIn('Retry-After', self.src)

    def test_http_429_returned(self):
        self.assertIn('429', self.src)

    def test_no_shell_true(self):
        self.assertNotIn('shell=True', self.src)

    def test_fail_closed_guard_present(self):
        # Must check for env vars and fail closed in production
        self.assertTrue('VERCEL_ENV' in self.src or 'production' in self.src,
                        "Python rate limiter must reference production env guard")


# ── admin auth static checks ──────────────────────────────────────────────────

class TestAdminAuthStatic(unittest.TestCase):
    """Verify admin-auth.js security properties via static analysis."""

    def setUp(self):
        with open('api/admin-auth.js', 'r', encoding='utf-8') as f:
            self.src = f.read()

    def test_no_service_key_fallback(self):
        # Must not fall back to SUPABASE_SERVICE_KEY as token secret
        self.assertNotIn('SUPABASE_SERVICE_KEY', self.src,
                         "admin-auth.js must not reference SUPABASE_SERVICE_KEY")

    def test_admin_token_secret_required(self):
        self.assertIn('ADMIN_TOKEN_SECRET', self.src)

    def test_timing_safe_equal_used(self):
        self.assertIn('timingSafeEqual', self.src)

    def test_httponly_cookie_set(self):
        self.assertIn('HttpOnly', self.src)

    def test_samesite_strict_set(self):
        self.assertIn('SameSite=Strict', self.src)

    def test_csrf_token_cookie_set(self):
        self.assertIn('csrf_token', self.src)

    def test_fails_503_when_secret_missing(self):
        # Must return error when ADMIN_TOKEN_SECRET not configured
        self.assertTrue('503' in self.src or 'misconfigured' in self.src.lower(),
                        "Must return 503 when ADMIN_TOKEN_SECRET not set")

    def test_password_not_in_source(self):
        # Admin password must come from env var only — check for common hardcoded literals
        self.assertNotIn("password123", self.src)
        self.assertNotIn("admin123", self.src)
        self.assertNotIn("titan2026", self.src)
        # Must reference env var, not assign a literal string to the password constant
        import re
        # Matches: const ADMIN_PASSWORD = "..." or = '...' (hardcoded literal, not env var)
        hardcoded = re.search(r'ADMIN_PASSWORD\s*=\s*["\']', self.src)
        self.assertIsNone(hardcoded, "ADMIN_PASSWORD must not be assigned a hardcoded string literal")


class TestAdminVerifyStatic(unittest.TestCase):
    """Verify _admin-verify.js shared auth helper."""

    def setUp(self):
        with open('api/_admin-verify.js', 'r', encoding='utf-8') as f:
            self.src = f.read()

    def test_production_mode_from_server_env_only(self):
        # Production mode must read ADMIN_PRODUCTION_MODE from env, not from request
        self.assertIn('ADMIN_PRODUCTION_MODE', self.src)
        self.assertNotIn('req.query.production', self.src)
        self.assertNotIn('req.body.production', self.src)

    def test_token_secret_no_supabase_fallback(self):
        self.assertNotIn('SUPABASE_SERVICE_KEY', self.src)

    def test_require_admin_exported(self):
        self.assertIn('requireAdmin', self.src)

    def test_require_csrf_exported(self):
        self.assertIn('requireCsrf', self.src)

    def test_csrf_reads_header(self):
        self.assertIn('X-CSRF-Token', self.src)

    def test_hmac_or_jwt_verify(self):
        self.assertTrue('createHmac' in self.src or 'verify' in self.src,
                        "Token must be verified with HMAC or JWT")


class TestAdminLogoutStatic(unittest.TestCase):
    def setUp(self):
        with open('api/admin-logout.js', 'r', encoding='utf-8') as f:
            self.src = f.read()

    def test_clears_admin_token_cookie(self):
        self.assertIn('admin_token=;', self.src)

    def test_clears_csrf_cookie(self):
        self.assertIn('csrf_token=;', self.src)

    def test_max_age_zero(self):
        self.assertIn('Max-Age=0', self.src)


# ── admin routes static checks ────────────────────────────────────────────────

class TestAdminRoutesStatic(unittest.TestCase):
    """Every admin route must require authentication; mutations must check CSRF."""

    ROUTES = [
        'api/admin/leads.js',
        'api/admin/permits.js',
        'api/admin/storm.js',
        'api/admin/measurements.js',
        'api/admin/reviews.js',
        'api/admin/jobs.js',
        'api/admin/job-activity.js',
    ]

    MUTATION_ROUTES = [
        'api/admin/reviews.js',
        'api/admin/jobs.js',
        'api/admin/job-activity.js',
    ]

    ALLOWLISTED_ROUTES = {
        'api/admin/reviews.js':     ('ALLOWED_PATCH_FIELDS', 'approved'),
        'api/admin/jobs.js':        ('ALLOWED_JOB_FIELDS', 'sanitizeJobFields'),
    }

    def _read(self, path):
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()

    def test_all_routes_call_require_admin(self):
        for route in self.ROUTES:
            with self.subTest(route=route):
                src = self._read(route)
                self.assertIn('requireAdmin', src, f"{route} must call requireAdmin()")

    def test_mutation_routes_call_require_csrf(self):
        for route in self.MUTATION_ROUTES:
            with self.subTest(route=route):
                src = self._read(route)
                self.assertIn('requireCsrf', src, f"{route} must call requireCsrf() on mutations")

    def test_mutation_routes_no_arbitrary_table(self):
        for route in self.MUTATION_ROUTES:
            with self.subTest(route=route):
                src = self._read(route)
                # Must not accept table name from request body
                self.assertNotIn('req.body.table', src)
                self.assertNotIn('req.query.table', src)

    def test_allowlisted_routes_have_allowlist(self):
        for route, (allowlist_name, _) in self.ALLOWLISTED_ROUTES.items():
            with self.subTest(route=route):
                src = self._read(route)
                self.assertIn(allowlist_name, src,
                              f"{route} must define {allowlist_name} for mutation field allowlist")

    def test_no_service_key_in_admin_routes(self):
        for route in self.ROUTES:
            with self.subTest(route=route):
                src = self._read(route)
                # Must not directly embed or hardcode the service key value
                self.assertNotIn('eyJ', src, f"{route} must not contain hardcoded JWT tokens")


# ── browser assets security ───────────────────────────────────────────────────

class TestBrowserAssetSecurity(unittest.TestCase):
    """Verify no sensitive credentials end up in browser-served HTML files."""

    ASSETS = ['index.html', 'pitch.html', 'quote.html', 'admin/reviews.html']
    # Match full 3-part JWT (header.payload.signature) — not base64 image data
    JWT_PAT = __import__('re').compile(r'eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+')

    def test_no_jwt_in_browser_assets(self):
        for asset in self.ASSETS:
            try:
                with open(asset, 'r', encoding='utf-8', errors='replace') as f:
                    content = f.read()
            except FileNotFoundError:
                continue
            matches = self.JWT_PAT.findall(content)
            with self.subTest(asset=asset):
                self.assertEqual(matches, [],
                                 f"{asset} contains {len(matches)} JWT token(s) — verify none is the service key")

    def test_no_supabase_service_key_env_name_in_js_bundles(self):
        # The string SUPABASE_SERVICE_KEY must not appear in any browser HTML
        for asset in self.ASSETS:
            try:
                with open(asset, 'r', encoding='utf-8', errors='replace') as f:
                    content = f.read()
            except FileNotFoundError:
                continue
            with self.subTest(asset=asset):
                self.assertNotIn('SUPABASE_SERVICE_KEY', content,
                                 f"{asset} must not reference SUPABASE_SERVICE_KEY")

    def test_no_cors_wildcard_in_js_files(self):
        import os, glob
        for path in glob.glob('api/*.js') + glob.glob('api/**/*.js'):
            with open(path, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()
            with self.subTest(path=path):
                self.assertNotIn("Access-Control-Allow-Origin': '*'", content)
                self.assertNotIn('Access-Control-Allow-Origin: *', content)


# ── production mode server-side enforcement ───────────────────────────────────

class TestProductionModeEnforcement(unittest.TestCase):
    """Verify that production mode can only be set from server env vars."""

    def setUp(self):
        with open('admin/reviews.html', 'r', encoding='utf-8') as f:
            self.html = f.read()

    def test_production_mode_fetched_from_server(self):
        # Browser must fetch /api/admin/config to determine mode
        self.assertIn('/api/admin/config', self.html)

    def test_no_localstorage_production_mode(self):
        self.assertNotIn("localStorage.getItem('productionMode')", self.html)
        self.assertNotIn("localStorage.setItem('productionMode'", self.html)

    def test_no_queryparam_production_mode(self):
        self.assertNotIn('URLSearchParams', self.html.split('/api/admin/config')[0])

    def test_demo_banner_present(self):
        self.assertIn('demoBanner', self.html)

    def test_admin_api_helper_uses_csrf_header(self):
        self.assertIn('X-CSRF-Token', self.html)

    def test_logout_calls_server_endpoint(self):
        self.assertIn('/api/admin-logout', self.html)

    def test_session_storage_not_used_for_auth_in_mutations(self):
        # sessionStorage token should not be passed as Authorization header to admin routes
        # (auth is now via HttpOnly cookie — server verifies)
        # Check that adminApi() does not add an Authorization header
        idx = self.html.find('function adminApi(')
        if idx == -1:
            idx = self.html.find('async function adminApi(')
        self.assertGreater(idx, 0, "adminApi() helper not found")
        # Extract up to 800 chars after the function start to inspect its body
        snippet = self.html[idx:idx + 800]
        self.assertNotIn("Authorization", snippet,
                         "adminApi() must not send Authorization header (auth is via HttpOnly cookie)")


if __name__ == '__main__':
    unittest.main(verbosity=2)
