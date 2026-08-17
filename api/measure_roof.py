"""
POC: address -> USGS 3DEP LiDAR -> isolated roof points -> plane fit -> geometry.

No building classification exists in this 3DEP project (verified empirically:
classification histogram is {1: unclassified, 2: ground, 7: low-noise} only,
no class 6). So building/roof isolation here uses height-above-ground +
spatial clustering instead of LAS Classification -- this is the fallback
path documented in the design spec, exercised here because OSM Overpass was
unreachable from this network during the POC run (separate issue, noted in
the spec; production should still try footprint-based isolation first).
"""
from __future__ import annotations

import json

import numpy as np
from scipy.spatial import cKDTree, ConvexHull
from sklearn.cluster import DBSCAN

from ept_fetch import crop_property

ADDRESS = "2324 MALLORY ST SW, Cedar Rapids, IA 52404"
LON, LAT = -91.661272122842, 41.955617442123
RESOURCE = "IA_Eastern_1_2019"
LIDAR_DATE = "2019-12 to 2020-06"  # IA_Eastern_1_2019 workunit collect window (verified via 3DEPElevationIndex)


def height_above_ground(xyz: np.ndarray, cls: np.ndarray) -> np.ndarray:
    """Reverted from a Delaunay TIN back to k=8 IDW (2026-08-14): the TIN
    version was tried as a fix for the false-flat/ground-contamination
    failures in VALIDATION_20_ADDRESS.md and produced near-identical slope
    numbers on the affected addresses (Mallory 1.3deg->1.5deg, Cornell
    2.1deg->1.9deg, Gilbert St 0.1deg->0.1deg) -- confirming the ground
    model was never the bottleneck. It also crashed (`No points given`)
    on sparse-ground-point crops instead of degrading gracefully like IDW
    does. Zero accuracy gain, real robustness loss -- reverted rather than
    kept as dead weight. Real bottleneck under investigation is DBSCAN
    cluster contamination (see split_bimodal_cluster in this file)."""
    ground = xyz[cls == 2]
    tree = cKDTree(ground[:, :2])
    dist, idx = tree.query(xyz[:, :2], k=8)
    w = 1.0 / np.clip(dist, 0.1, None)
    ground_z = np.sum(ground[idx, 2] * w, axis=1) / np.sum(w, axis=1)
    return xyz[:, 2] - ground_z


def fit_plane_ransac(points: np.ndarray, n_iters=300, threshold=0.15, rng=None):
    """Minimal RANSAC plane fit (no external ransac dep needed for 3 points).
    Returns (normal, d, inlier_mask, rmse)."""
    rng = rng or np.random.default_rng(42)
    best_inliers = None
    best_count = -1
    n = len(points)
    for _ in range(n_iters):
        idx = rng.choice(n, 3, replace=False)
        p0, p1, p2 = points[idx]
        v1, v2 = p1 - p0, p2 - p0
        normal = np.cross(v1, v2)
        norm = np.linalg.norm(normal)
        if norm < 1e-6:
            continue
        normal = normal / norm
        d = -np.dot(normal, p0)
        dist = np.abs(points @ normal + d)
        inliers = dist < threshold
        count = inliers.sum()
        if count > best_count:
            best_count = count
            best_inliers = inliers
            best_normal, best_d = normal, d
    # refine with least-squares over inliers
    pts_in = points[best_inliers]
    centroid = pts_in.mean(axis=0)
    _, _, vh = np.linalg.svd(pts_in - centroid)
    normal = vh[2]
    if normal[2] < 0:
        normal = -normal
    d = -np.dot(normal, centroid)
    dist = np.abs(points @ normal + d)
    inliers = dist < threshold
    rmse = float(np.sqrt(np.mean(dist[inliers] ** 2)))
    return normal, d, inliers, rmse


def pitch_from_normal(normal: np.ndarray) -> tuple[float, str]:
    nx, ny, nz = normal
    horiz = np.hypot(nx, ny)
    slope_angle = np.degrees(np.arctan2(horiz, abs(nz)))
    rise_per_12 = 12 * np.tan(np.radians(slope_angle))
    return slope_angle, f"{rise_per_12:.1f}:12"


def _local_slope_deg(points: np.ndarray, tree: cKDTree, idx: np.ndarray, k: int) -> np.ndarray:
    """Fast per-point local slope via PCA/SVD normal on each point's k nearest
    neighbors -- same normal-from-SVD math fit_plane_ransac uses for its final
    refit, just without the iterative RANSAC outlier search, since this needs
    to run once per point (thousands of times) rather than ~15-300 times total.
    Not a change to fit_plane_ransac itself, a separate lighter-weight pass."""
    n = len(points)
    slopes = np.empty(n)
    for i in range(n):
        neighborhood = points[idx[i, :k]]
        centroid = neighborhood.mean(axis=0)
        _, _, vh = np.linalg.svd(neighborhood - centroid)
        normal = vh[2]
        if normal[2] < 0:
            normal = -normal
        slopes[i], _ = pitch_from_normal(normal)
    return slopes


def split_bimodal_cluster(
    cluster_pts: np.ndarray,
    n_trials: int = 15,
    subsample_size: int = 200,
    flat_threshold_deg: float = 5.0,
    min_population: int = 3,
    rng=None,
) -> dict:
    """Diagnostic for the DBSCAN-cluster-contamination hypothesis (see
    VALIDATION_20_ADDRESS.md): fit fit_plane_ransac to `n_trials` random
    `subsample_size`-point subsamples of the cluster and collect each
    subsample's slope. If enough trials land near-flat (<flat_threshold_deg)
    AND enough land sloped, the cluster is a mix of two populations -- the
    signature of a real roof merged with an adjacent flat surface (driveway,
    patio, flat neighboring roof) by DBSCAN's eps. If bimodal, classifies
    every point in the full cluster by local (k-NN/SVD) slope and returns
    only the sloped sub-population for the caller to run the real pipeline
    on. This function does not touch fit_plane_ransac or pitch_from_normal
    themselves -- it only calls them."""
    rng = rng or np.random.default_rng(7)
    n = len(cluster_pts)
    size = min(subsample_size, n)

    trial_slopes = []
    for _ in range(n_trials):
        sample_idx = rng.choice(n, size, replace=False)
        sample = cluster_pts[sample_idx]
        try:
            normal, _, _, _ = fit_plane_ransac(sample, n_iters=100, rng=rng)
        except Exception:
            continue
        slope_deg, _ = pitch_from_normal(normal)
        trial_slopes.append(slope_deg)
    trial_slopes = np.array(trial_slopes)

    n_flat = int((trial_slopes < flat_threshold_deg).sum())
    n_sloped = int((trial_slopes >= flat_threshold_deg).sum())
    is_bimodal = n_flat >= min_population and n_sloped >= min_population

    result = {
        "trial_slopes": trial_slopes.tolist(),
        "n_flat_trials": n_flat,
        "n_sloped_trials": n_sloped,
        "is_bimodal": is_bimodal,
        "sloped_points": None,
    }
    if not is_bimodal:
        return result

    k = min(30, n)
    tree = cKDTree(cluster_pts[:, :2])
    _, idx = tree.query(cluster_pts[:, :2], k=k)
    if k == 1:
        idx = idx.reshape(-1, 1)
    point_slopes = _local_slope_deg(cluster_pts, tree, idx, k)
    result["point_slopes"] = point_slopes.tolist()
    result["sloped_points"] = cluster_pts[point_slopes >= flat_threshold_deg]
    return result


def polygon_area_sqm(points_2d: np.ndarray) -> float:
    hull = ConvexHull(points_2d)
    return hull.volume  # 2D "volume" from scipy ConvexHull is the area


def main():
    xyz, cls, center, node_keys = crop_property(RESOURCE, LON, LAT, half_extent_m=35.0)
    print(f"[fetch] {len(node_keys)} EPT nodes, {len(xyz)} points in 70m x 70m crop")

    hag = height_above_ground(xyz, cls)
    above = (hag > 1.8) & (hag < 20) & (cls != 7)
    candidates = xyz[above]
    print(f"[filter] {len(candidates)} candidate above-ground points")

    if len(candidates) < 30:
        print(json.dumps({"error": "insufficient points after filtering", "confidence": 0.0}))
        return

    clustering = DBSCAN(eps=2.5, min_samples=8).fit(candidates[:, :2])
    labels = clustering.labels_
    unique_labels = [l for l in set(labels) if l != -1]
    print(f"[cluster] {len(unique_labels)} candidate structures found in crop")

    # pick cluster whose centroid is nearest the address point (target building,
    # not a neighboring garage/shed/tree canopy also inside the crop radius)
    best_label, best_dist = None, float("inf")
    for l in unique_labels:
        pts = candidates[labels == l]
        centroid = pts[:, :2].mean(axis=0)
        d = np.hypot(centroid[0] - center[0], centroid[1] - center[1])
        if d < best_dist:
            best_dist, best_label = d, l

    roof_pts = candidates[labels == best_label]
    print(f"[select] target structure: {len(roof_pts)} points, {best_dist:.1f}m from address point")

    footprint_sqm = polygon_area_sqm(roof_pts[:, :2])

    # simple gable assumption for V1: try 1 plane, and 2-plane split (RANSAC,
    # remove inliers, refit remainder) -- report whichever leaves fewer
    # unexplained points, which is the real signal for "is this actually
    # more complex than a single/double-pitch gable"
    normal1, d1, inliers1, rmse1 = fit_plane_ransac(roof_pts)
    remainder = roof_pts[~inliers1]
    planes = [{"normal": normal1, "points": roof_pts[inliers1], "rmse": rmse1}]

    used_two_planes = False
    if len(remainder) > 0.15 * len(roof_pts):
        normal2, d2, inliers2, rmse2 = fit_plane_ransac(remainder)
        if inliers2.sum() > 0.1 * len(roof_pts):
            planes.append({"normal": normal2, "points": remainder[inliers2], "rmse": rmse2})
            used_two_planes = True

    plane_results = []
    total_roof_area = 0.0
    for i, p in enumerate(planes):
        slope_deg, pitch_label = pitch_from_normal(p["normal"])
        plane_footprint = polygon_area_sqm(p["points"][:, :2])
        plane_area = plane_footprint / max(np.cos(np.radians(slope_deg)), 0.2)
        total_roof_area += plane_area
        plane_results.append({
            "plane_id": i,
            "point_count": int(len(p["points"])),
            "slope_degrees": round(float(slope_deg), 1),
            "pitch": pitch_label,
            "area_sqft": round(plane_area * 10.7639, 1),
            "rmse_m": round(p["rmse"], 3),
        })

    explained_frac = sum(len(p["points"]) for p in planes) / len(roof_pts)
    point_density = len(roof_pts) / max(footprint_sqm, 1)

    flags = []
    if point_density < 2:
        flags.append("low_point_density")
    if explained_frac < 0.75:
        flags.append("complex_geometry")
    if max(pl["rmse"] for pl in planes) > 0.25:
        flags.append("low_plane_fit_quality")
    flags.append("lidar_age_over_5yr")  # 2019/2020 collection vs current date -- always true for this project, will age out only when Iowa flies a newer statewide pass

    confidence = 0.9
    confidence -= 0.25 if "complex_geometry" in flags else 0
    confidence -= 0.15 if "low_plane_fit_quality" in flags else 0
    confidence -= 0.1 if "low_point_density" in flags else 0
    confidence -= 0.05  # lidar age
    confidence = max(0.0, min(0.95, confidence))

    result = {
        "address": ADDRESS,
        "footprint_sqft": round(footprint_sqm * 10.7639, 0),
        "roof_area_sqft": round(total_roof_area * 10.7639, 0),
        "squares": round(total_roof_area * 10.7639 / 100, 1),
        "pitch_primary": plane_results[0]["pitch"],
        "planes": plane_results,
        "two_plane_gable_detected": used_two_planes,
        "confidence": round(confidence, 2),
        "confidence_flags": flags,
        "manual_verification_recommended": confidence < 0.6,
        "lidar_date": LIDAR_DATE,
        "point_density": round(point_density, 2),
        "source": "USGS 3DEP QL2 (IA_Eastern_1_2019)",
        "isolation_method": "height-above-ground + DBSCAN cluster nearest address point (no LAS building classification available in this project -- see spec)",
    }
    print(json.dumps(result, indent=2))

    with open("result.json", "w") as f:
        json.dump(result, f, indent=2)

    # visual proof
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from mpl_toolkits.mplot3d import Axes3D  # noqa

    fig = plt.figure(figsize=(12, 5))
    ax1 = fig.add_subplot(121, projection="3d")
    ax1.scatter(xyz[cls == 2, 0] - center[0], xyz[cls == 2, 1] - center[1], xyz[cls == 2, 2],
                s=1, c="tan", label="ground (class 2)")
    colors = ["crimson", "royalblue", "darkorange"]
    for i, p in enumerate(planes):
        pts = p["points"]
        ax1.scatter(pts[:, 0] - center[0], pts[:, 1] - center[1], pts[:, 2],
                    s=3, c=colors[i % 3], label=f"roof plane {i} ({plane_results[i]['pitch']})")
    ax1.set_title(f"{ADDRESS}\nUSGS 3DEP point cloud")
    ax1.legend(fontsize=7)
    ax1.set_xlabel("m"); ax1.set_ylabel("m"); ax1.set_zlabel("elev (m)")

    ax2 = fig.add_subplot(122)
    sc = ax2.scatter(candidates[:, 0] - center[0], candidates[:, 1] - center[1], c=labels, cmap="tab10", s=4)
    ax2.scatter([0], [0], marker="*", s=200, c="black", label="geocoded address point")
    ax2.set_title("DBSCAN structure clustering (top-down)")
    ax2.set_aspect("equal")
    ax2.legend(fontsize=7)
    plt.tight_layout()
    plt.savefig("roof_measurement_proof.png", dpi=150)
    print("\nSaved visual proof -> roof_measurement_proof.png")


if __name__ == "__main__":
    main()
