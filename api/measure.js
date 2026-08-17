const SUPABASE_URL = 'https://yfscfuyxbluidykmpjod.supabase.co';
const SUPABASE_KEY = process.env.SUPABASE_SERVICE_KEY || 'sb_publishable_DrqBo5ukYx-8hUOtDLISbQ_aFeG_A66';
const REGRID_KEY = process.env.REGRID_API_KEY;

function haversineMeters(lat1, lon1, lat2, lon2) {
  const R = 6371000;
  const toR = d => d * Math.PI / 180;
  const dLat = toR(lat2 - lat1), dLon = toR(lon2 - lon1);
  const a = Math.sin(dLat / 2) ** 2 + Math.cos(toR(lat1)) * Math.cos(toR(lat2)) * Math.sin(dLon / 2) ** 2;
  return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

function polygonMetrics(coords) {
  if (!coords || coords.length < 3) return null;
  const origin = coords[0];
  const toR = d => d * Math.PI / 180;
  const R = 6371000;

  const pts = coords.map(c => ({
    x: R * toR(c.lon - origin.lon) * Math.cos(toR(origin.lat)),
    y: R * toR(c.lat - origin.lat)
  }));

  let area = 0, perim = 0;
  for (let i = 0; i < pts.length - 1; i++) {
    area += pts[i].x * pts[i + 1].y - pts[i + 1].x * pts[i].y;
    perim += haversineMeters(coords[i].lat, coords[i].lon, coords[i + 1].lat, coords[i + 1].lon);
  }

  const sqM = Math.abs(area) / 2;
  return {
    areaSqFt: Math.round(sqM * 10.7639),
    perimeterFt: Math.round(perim * 3.28084)
  };
}

async function geocode(address) {
  // Try Census current benchmark first
  const censusUrl = `https://geocoding.geo.census.gov/geocoder/locations/onelineaddress?address=${encodeURIComponent(address)}&benchmark=Public_AR_Current&format=json`;
  const censusRes = await fetch(censusUrl, { signal: AbortSignal.timeout(6000) }).catch(() => null);
  if (censusRes?.ok) {
    const data = await censusRes.json();
    const match = data.result?.addressMatches?.[0];
    if (match) return { lat: match.coordinates.y, lng: match.coordinates.x, matchedAddress: match.matchedAddress };
  }

  // Fall back to Nominatim (handles new subdivisions Census hasn't indexed yet)
  const nomUrl = `https://nominatim.openstreetmap.org/search?q=${encodeURIComponent(address)}&format=json&limit=1&addressdetails=1`;
  const nomRes = await fetch(nomUrl, { headers: { 'User-Agent': 'TitanContractingOS/1.0' }, signal: AbortSignal.timeout(6000) }).catch(() => null);
  if (nomRes?.ok) {
    const data = await nomRes.json();
    const match = data[0];
    if (match) return { lat: parseFloat(match.lat), lng: parseFloat(match.lon), matchedAddress: match.display_name };
  }

  throw new Error('Address not found');
}

async function tryFetch(url, opts, timeoutMs) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(url, { ...opts, signal: controller.signal });
    clearTimeout(timer);
    return res;
  } catch (e) {
    clearTimeout(timer);
    throw e;
  }
}

async function getRegrid(lat, lng) {
  if (!REGRID_KEY) { console.log('regrid: no key'); return null; }
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 6000);
  try {
    const url = `https://app.regrid.com/api/v2/parcels/point?lat=${lat}&lon=${lng}&token=${REGRID_KEY}`;
    const res = await fetch(url, { headers: { 'Accept': 'application/json' }, signal: controller.signal });
    clearTimeout(timer);
    if (!res.ok) { console.log('regrid: http error', res.status); return null; }
    const data = await res.json();
    const feature = data?.parcels?.features?.[0];
    if (!feature) return null;
    const props = feature.properties;
    const sqft = props.ll_gissqft || props.sqft || null;
    const stories = parseInt(props.stories) || 1;
    if (!sqft || sqft < 200) return null;
    const parcelGeojson = feature.geometry || null;
    return {
      areaSqFt: Math.round(sqft),
      perimeterFt: null,
      osmStories: stories,
      source: 'regrid',
      parcelGeojson
    };
  } catch (e) {
    clearTimeout(timer);
    console.log('regrid error:', e.message);
    return null;
  }
}

async function getLidarMeasurement(lat, lng, parcelGeojson) {
  try {
    // Use custom domain to avoid Vercel deployment-protection 401 on raw deployment URLs
    const baseUrl = process.env.PRODUCTION_URL || (process.env.VERCEL_URL
      ? `https://${process.env.VERCEL_URL}`
      : 'http://localhost:3000');
    const res = await fetch(`${baseUrl}/api/measure_lidar`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ lat, lon: lng, parcel_geojson: parcelGeojson }),
      signal: AbortSignal.timeout(90000)
    });
    if (!res.ok) { console.log('lidar: http error', res.status); return null; }
    const data = await res.json();
    console.log('lidar: confidence:', data.confidence, 'error:', data.error);
    if (data.error || data.confidence < 0.4) return null;
    return data;
  } catch (e) {
    console.log('lidar error:', e.message);
    return null;
  }
}

async function getBuilding(lat, lng) {
  const overpassQuery = `[out:json][timeout:6];way["building"](around:80,${lat},${lng});out geom tags;`;
  const overpassMirrors = [
    'https://overpass-api.de/api/interpreter',
    'https://overpass.kumi.systems/api/interpreter',
    'https://maps.mail.ru/osm/tools/overpass/api/interpreter'
  ];

  // Try all sources in parallel — first to succeed wins
  const overpassAttempts = overpassMirrors.map(mirror =>
    tryFetch(`${mirror}?data=${encodeURIComponent(overpassQuery)}`, {}, 7000)
      .then(r => r.ok ? r.json() : Promise.reject())
      .then(d => {
        const buildings = (d.elements || []).filter(e => e.geometry?.length > 2);
        if (!buildings.length) return Promise.reject(new Error('no buildings'));
        const best = buildings.reduce((a, b) => {
          const dA = haversineMeters(lat, lng, a.geometry[0].lat, a.geometry[0].lon);
          const dB = haversineMeters(lat, lng, b.geometry[0].lat, b.geometry[0].lon);
          return dA <= dB ? a : b;
        });
        const metrics = polygonMetrics(best.geometry);
        if (!metrics) return Promise.reject(new Error('bad polygon'));
        // Build GeoJSON polygon for LiDAR isolation
        const coords = best.geometry.map(pt => [pt.lon, pt.lat]);
        if (coords[0][0] !== coords[coords.length-1][0] || coords[0][1] !== coords[coords.length-1][1]) coords.push(coords[0]);
        const buildingGeojson = { type: 'Polygon', coordinates: [coords] };
        return { ...metrics, osmStories: parseInt(best.tags?.['building:levels']) || null, buildingGeojson };
      })
  );

  const nominatimAttempt = tryFetch(
    `https://nominatim.openstreetmap.org/reverse?lat=${lat}&lon=${lng}&format=json&polygon_geojson=1&zoom=18`,
    { headers: { 'User-Agent': 'TitanContractingOS/1.0' } },
    8000
  )
    .then(r => r.ok ? r.json() : Promise.reject())
    .then(data => {
      const geom = data.geojson;
      if (!geom || geom.type !== 'Polygon' || !geom.coordinates?.[0]?.length) return Promise.reject(new Error('no polygon'));
      const coords = geom.coordinates[0].map(([lon, lat]) => ({ lat, lon }));
      const metrics = polygonMetrics(coords);
      if (!metrics) return Promise.reject(new Error('bad polygon'));
      return { ...metrics, osmStories: null, buildingGeojson: geom };
    });

  try {
    return await Promise.any([...overpassAttempts, nominatimAttempt]);
  } catch {
    return null;
  }
}


function deriveStats(footprintSqFt, perimeterFt, stories) {
  // Pitch factor: Iowa residential median ~5/12 = factor ~1.08
  const pitchFactor = 1.08;
  const roofAreaSqFt = Math.round(footprintSqFt * pitchFactor);
  const roofSquares = +(roofAreaSqFt / 100).toFixed(1);

  // Siding area: perimeter × wall height × stories, discount 25% for windows/doors
  const wallHeight = 9; // ft per story
  const sidingArea = Math.round(perimeterFt * wallHeight * stories * 0.75);

  // Gutter = perimeter (eave length approximation)
  const gutterLength = perimeterFt;

  // Complexity based on building shape
  const ratio = perimeterFt / Math.sqrt(footprintSqFt * 4);
  const complexity = ratio > 1.4 ? 'complex' : ratio > 1.1 ? 'moderate' : 'simple';

  return { roofAreaSqFt, roofSquares, pitchEstimate: '4–6/12', sidingArea, gutterLength, complexity };
}

function sqftToBucket(sqft) {
  if (sqft < 1000) return 'Under 1,000';
  if (sqft < 1500) return '1,000 – 1,500';
  if (sqft < 2000) return '1,500 – 2,000';
  if (sqft < 2500) return '2,000 – 2,500';
  if (sqft < 3000) return '2,500 – 3,000';
  return '3,000+';
}

function sqftToGutterBucket(sqft) {
  if (sqft < 1000) return 'Under 1,000';
  if (sqft < 1800) return '1,000 – 1,800';
  if (sqft < 2500) return '1,800 – 2,500';
  if (sqft < 3500) return '2,500 – 3,500';
  return '3,500+';
}

function storiesToBucket(n) {
  if (n >= 2.5) return '2.5+ stories';
  if (n >= 2) return '2 stories';
  if (n >= 1.5) return '1.5 stories';
  return '1 story';
}

async function checkCache(address) {
  const normalized = address.toLowerCase().replace(/\s+/g, ' ').trim();
  const res = await fetch(`${SUPABASE_URL}/rest/v1/property_measurements?address_normalized=eq.${encodeURIComponent(normalized)}&order=created_at.desc&limit=1`, {
    headers: { 'apikey': SUPABASE_KEY, 'Authorization': `Bearer ${SUPABASE_KEY}` }
  });
  const rows = await res.json();
  if (rows?.length) return rows[0];
  return null;
}

async function saveCache(row) {
  await fetch(`${SUPABASE_URL}/rest/v1/property_measurements`, {
    method: 'POST',
    headers: {
      'apikey': SUPABASE_KEY,
      'Authorization': `Bearer ${SUPABASE_KEY}`,
      'Content-Type': 'application/json',
      'Prefer': 'return=minimal'
    },
    body: JSON.stringify(row)
  }).catch(() => {}); // cache write failures are non-fatal
}

export default async function handler(req, res) {
  if (req.method !== 'POST') return res.status(405).json({ error: 'Method not allowed' });

  const rawAddress = req.body?.address;
  if (typeof rawAddress !== 'string') return res.status(400).json({ error: 'Address required' });
  const address = rawAddress.trim().replace(/\s+/g, ' ');
  if (!address) return res.status(400).json({ error: 'Address required' });
  if (address.length > 500) return res.status(400).json({ error: 'Address too long' });

  const start = Date.now();

  try {
    // Check cache first
    const cached = await checkCache(address).catch(() => null);
    if (cached) {
      return res.json({ ...cached, cached: true });
    }

    // Geocode
    const { lat, lng, matchedAddress } = await geocode(address);
    const normalizedAddress = address.toLowerCase().replace(/\s+/g, ' ').trim();

    // Regrid + OSM in parallel for parcel data
    const [regrid, osm] = await Promise.all([
      getRegrid(lat, lng).catch(() => null),
      getBuilding(lat, lng).catch(() => null)
    ]);

    const building = regrid || osm;
    const gisSource = regrid ? 'regrid' : 'census+osm';

    // Try LiDAR measurement — parcel from Regrid preferred, OSM building footprint as fallback
    const isolationGeojson = regrid?.parcelGeojson || osm?.buildingGeojson || null;
    const lidar = await getLidarMeasurement(lat, lng, isolationGeojson);

    let result;
    if (lidar) {
      // LiDAR path — real geometry from USGS 3DEP
      const stories = building?.osmStories || 1;
      const footprintSqFt = lidar.footprint_sqft || building?.areaSqFt || null;
      const perimeterFt = footprintSqFt ? Math.round(4 * Math.sqrt(footprintSqFt)) : null;
      result = {
        address: matchedAddress,
        address_normalized: normalizedAddress,
        lat, lng,
        footprint_sqft: footprintSqFt,
        perimeter_ft: perimeterFt,
        roof_area_sqft: lidar.roof_area_sqft,
        roof_squares: lidar.squares,
        estimated_pitch: lidar.pitch_primary,
        estimated_stories: stories,
        gutter_length: perimeterFt,
        siding_area: perimeterFt ? Math.round(perimeterFt * 9 * stories * 0.75) : null,
        complexity: lidar.confidence_flags.includes('complex_geometry') ? 'complex' : 'simple',
        size_bucket: footprintSqFt ? sqftToBucket(footprintSqFt) : null,
        gutter_size_bucket: footprintSqFt ? sqftToGutterBucket(footprintSqFt) : null,
        stories_bucket: storiesToBucket(stories),
        confidence: Math.round(lidar.confidence * 100),
        confidence_flags: lidar.confidence_flags,
        lidar_date: lidar.lidar_date,
        lidar_source: lidar.source,
        measurement_method: 'lidar',
        manual_verification_required: true,
        gis_source: 'usgs_3dep',
        processing_time_ms: Date.now() - start,
        found: true
      };
    } else if (!building || building.areaSqFt < 200) {
      result = {
        address: matchedAddress,
        address_normalized: normalizedAddress,
        lat, lng,
        footprint_sqft: null,
        roof_area_sqft: null,
        roof_squares: null,
        estimated_pitch: '4–6/12',
        estimated_stories: 1,
        gutter_length: null,
        siding_area: null,
        complexity: null,
        size_bucket: null,
        gutter_size_bucket: null,
        stories_bucket: null,
        confidence: 30,
        measurement_method: 'unavailable',
        manual_verification_required: true,
        gis_source: gisSource,
        processing_time_ms: Date.now() - start,
        found: false
      };
    } else {
      // Regrid/OSM fallback — derived stats, NOT LiDAR
      const stories = building.osmStories || 1;
      const footprintSqFt = building.areaSqFt;
      const perimeterFt = building.perimeterFt || Math.round(4 * Math.sqrt(footprintSqFt));
      const stats = deriveStats(footprintSqFt, perimeterFt, stories);
      result = {
        address: matchedAddress,
        address_normalized: normalizedAddress,
        lat, lng,
        footprint_sqft: footprintSqFt,
        perimeter_ft: perimeterFt,
        roof_area_sqft: stats.roofAreaSqFt,
        roof_squares: stats.roofSquares,
        estimated_pitch: stats.pitchEstimate,
        estimated_stories: stories,
        gutter_length: stats.gutterLength,
        siding_area: stats.sidingArea,
        complexity: stats.complexity,
        size_bucket: sqftToBucket(footprintSqFt),
        gutter_size_bucket: sqftToGutterBucket(footprintSqFt),
        stories_bucket: storiesToBucket(stories),
        confidence: regrid ? 85 : 72,
        measurement_method: regrid ? 'regrid_estimate' : 'osm_estimate',
        manual_verification_required: true,
        gis_source: gisSource,
        processing_time_ms: Date.now() - start,
        found: true
      };
    }

    await saveCache(result);
    return res.json(result);

  } catch (err) {
    console.error('measure error:', err.message);
    return res.status(500).json({ error: err.message || 'Measurement failed' });
  }
}
