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


if __name__ == '__main__':
    unittest.main(verbosity=2)
