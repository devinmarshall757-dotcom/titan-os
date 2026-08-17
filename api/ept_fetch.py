"""
Minimal EPT (Entwine Point Tile) crop client -- no PDAL required.

Recursively walks a USGS 3DEP EPT resource's hierarchy (root ept.json +
ept-hierarchy/*.json pointer files), finds every octree node whose cell
overlaps a small target bounding box, downloads only those node .laz files
(ept-data/{key}.laz), decodes them with laspy+lazrs, and returns a merged,
bbox-cropped point array.

This is what PDAL's readers.ept does internally. Reimplemented here in pure
Python because PDAL has no Windows pip wheel on this machine (needs a C++
toolchain / conda-forge) -- see the design doc for the production recommendation.
"""
from __future__ import annotations

import io
import json
import os
from dataclasses import dataclass
from pathlib import Path


class LidarCoverageError(Exception):
    """Raised when LiDAR data is unavailable or empty for a location.
    Safe to surface publicly — contains no internal paths or upstream details."""

import laspy
import numpy as np
import requests

BASE = "https://s3-us-west-2.amazonaws.com/usgs-lidar-public/{resource}"

# Disk cache keyed by {resource}/{node_key} -- NOT by address or parcel.
# Per the spec: most of the byte cost of any single lookup is coarse,
# state-wide-shared octree nodes that should only ever be fetched once per
# resource, plus deep nodes that are shared across an entire ~150m
# neighborhood. Caching by node key (rather than by address) is what
# actually makes repeat lookups free -- caching by address would re-download
# the same shared nodes for every new property.
CACHE_DIR = Path(os.environ.get("EPT_CACHE_DIR", "/tmp/.ept_cache"))


@dataclass
class EptResource:
    resource: str
    bounds: list  # [minx,miny,minz,maxx,maxy,maxz] in EPT's srs (EPSG:3857 for USGS public bucket)
    schema: list
    srs_wkt: str
    points_total: int

    @property
    def side(self) -> float:
        return self.bounds[3] - self.bounds[0]


def load_resource(resource: str) -> EptResource:
    url = BASE.format(resource=resource) + "/ept.json"
    meta = requests.get(url, timeout=30).json()
    return EptResource(
        resource=resource,
        bounds=meta["bounds"],
        schema=meta["schema"],
        srs_wkt=meta["srs"]["wkt"],
        points_total=meta["points"],
    )


def node_bounds(ept: EptResource, key: str) -> tuple[float, float, float, float, float, float]:
    d, x, y, z = (int(p) for p in key.split("-"))
    n = 2**d
    cw = ept.side / n
    minx, miny, minz = ept.bounds[0], ept.bounds[1], ept.bounds[2]
    return (
        minx + x * cw, miny + y * cw, minz + z * cw,
        minx + (x + 1) * cw, miny + (y + 1) * cw, minz + (z + 1) * cw,
    )


def _overlaps(a, b) -> bool:
    ax0, ay0, az0, ax1, ay1, az1 = a
    bx0, by0, bz0, bx1, by1, bz1 = b
    return ax0 < bx1 and ax1 > bx0 and ay0 < by1 and ay1 > by0


def _hierarchy_cache_path(resource: str, key: str) -> Path:
    return CACHE_DIR / resource / "hierarchy" / f"{key}.json"


def _node_cache_path(resource: str, key: str) -> Path:
    return CACHE_DIR / resource / "data" / f"{key}.laz"


def find_overlapping_nodes(ept: EptResource, target_bbox_3857: tuple, session: requests.Session) -> list[str]:
    """Walk the hierarchy (following -1 pointers as needed) and return every
    node key whose octree cell overlaps target_bbox_3857 (minx,miny,minz,maxx,maxy,maxz).
    Hierarchy step files are small and shared across many lookups (a coarse
    node's hierarchy file covers a huge area), so they're cached too."""
    found = []

    def walk(key: str):
        cache_path = _hierarchy_cache_path(ept.resource, key)
        if cache_path.exists():
            step = json.loads(cache_path.read_text())
        else:
            url = BASE.format(resource=ept.resource) + f"/ept-hierarchy/{key}.json"
            resp = session.get(url, timeout=30)
            resp.raise_for_status()
            step = resp.json()
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps(step))
        for k, count in step.items():
            nb = node_bounds(ept, k)
            if not _overlaps(nb, target_bbox_3857):
                continue
            if count == -1:
                walk(k)  # deeper hierarchy file, same absolute key
            else:
                found.append(k)

    walk("0-0-0-0")
    return found


def download_node(ept: EptResource, key: str, session: requests.Session) -> np.ndarray:
    cache_path = _node_cache_path(ept.resource, key)
    if cache_path.exists():
        raw = cache_path.read_bytes()
    else:
        url = BASE.format(resource=ept.resource) + f"/ept-data/{key}.laz"
        resp = session.get(url, timeout=60)
        resp.raise_for_status()
        raw = resp.content
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_bytes(raw)
    las = laspy.read(io.BytesIO(raw))
    xyz = np.column_stack([las.x, las.y, las.z])
    classification = np.asarray(las.classification)
    return xyz, classification


def crop_property(resource: str, lon: float, lat: float, half_extent_m: float = 45.0):
    """Full pipeline: WGS84 address point -> EPT resource -> cropped, classified
    (x,y,z,classification) point array in EPSG:3857 meters, restricted to a
    square of side 2*half_extent_m centered on the point."""
    import pyproj

    ept = load_resource(resource)
    t = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)
    cx, cy = t.transform(lon, lat)
    target_bbox = (cx - half_extent_m, cy - half_extent_m, ept.bounds[2],
                   cx + half_extent_m, cy + half_extent_m, ept.bounds[5])

    session = requests.Session()
    node_keys = find_overlapping_nodes(ept, target_bbox, session)

    if not node_keys:
        raise LidarCoverageError("No EPT nodes overlap this location — LiDAR coverage unavailable here")

    all_xyz, all_cls = [], []
    for key in node_keys:
        xyz_node, cls_node = download_node(ept, key, session)
        if xyz_node is None or len(xyz_node) == 0:
            continue
        all_xyz.append(xyz_node)
        all_cls.append(cls_node)

    if not all_xyz:
        raise LidarCoverageError("EPT nodes returned no point data for this location")

    xyz = np.concatenate(all_xyz, axis=0)
    cls = np.concatenate(all_cls, axis=0)

    if len(xyz) != len(cls):
        raise LidarCoverageError("Point cloud integrity error — xyz/classification length mismatch")

    mask = (
        (xyz[:, 0] >= target_bbox[0]) & (xyz[:, 0] <= target_bbox[3]) &
        (xyz[:, 1] >= target_bbox[1]) & (xyz[:, 1] <= target_bbox[4])
    )
    xyz_cropped = xyz[mask]
    cls_cropped = cls[mask]

    if len(xyz_cropped) == 0:
        raise LidarCoverageError("No points within crop boundary — location is at coverage edge or outside coverage area")

    return xyz_cropped, cls_cropped, (cx, cy), node_keys


if __name__ == "__main__":
    import sys

    lon, lat = float(sys.argv[1]), float(sys.argv[2])
    xyz, cls, center, keys = crop_property("IA_Eastern_1_2019", lon, lat)
    print(f"nodes fetched: {len(keys)}")
    print(f"points in {90}m x {90}m crop: {len(xyz)}")
    print(f"z range: {xyz[:,2].min():.2f} to {xyz[:,2].max():.2f} m")
    import numpy as np
    uniq, counts = np.unique(cls, return_counts=True)
    print("classification histogram:", dict(zip(uniq.tolist(), counts.tolist())))
