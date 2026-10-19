"""External-engine worker: infer floor from grid size and template matches, preserve fixed-node semantics."""
import argparse
import json
from pathlib import Path
import sys


def detect_grid_size(points, width):
    """Estimate occupied grid extent from repeated, near-square node spacing."""
    import numpy as np

    best = None
    for step in np.arange(width * .05, width * .195, max(1., width / 640)):
        seen_x = set()
        for origin_x in points[:, 0]:
            x = (points[:, 0] - origin_x) / step
            mask_x = np.abs(x - np.round(x)) < .10
            key_x = mask_x.tobytes()
            if key_x in seen_x:
                continue
            seen_x.add(key_x)
            aligned_x = points[mask_x]
            if len(aligned_x) < 10:
                continue
            seen_y = set()
            for origin_y in aligned_x[:, 1]:
                y = (aligned_x[:, 1] - origin_y) / step
                mask_y = np.abs(y - np.round(y)) < .10
                key_y = mask_y.tobytes()
                if key_y in seen_y:
                    continue
                seen_y.add(key_y)
                aligned = aligned_x[mask_y]
                cells = set(map(tuple, np.round(
                    (aligned - [origin_x, origin_y]) / step).astype(int)))
                # Isolated HUD detections do not establish a grid axis.
                for _ in range(2):
                    cells = {q for q in cells
                             if sum(a == q[0] for a, b in cells) >= 2
                             and sum(b == q[1] for a, b in cells) >= 2}
                if not cells:
                    continue
                columns = max(a for a, b in cells) - min(a for a, b in cells) + 1
                rows = max(b for a, b in cells) - min(b for a, b in cells) + 1
                if not (3 <= columns <= 11 and 3 <= rows <= 6):
                    continue
                score = len(cells) - .35 * columns * rows
                if best is None or score > best[0]:
                    best = (score, columns, rows)
    return {'columns': int(best[1]), 'rows': int(best[2])} if best else None


def recognize(repository, image_path):
    sys.path.insert(0, str(Path(repository).resolve()))
    import cv2
    from vision.recognition import RecognitionPipeline
    image = cv2.imread(image_path)
    if image is None:
        raise ValueError('invalid_image')
    pipeline = RecognitionPipeline(repository)
    # Keep upstream detection shared across all floor hypotheses.
    matcher = pipeline.matcher
    global_nodes = pipeline.node_type_detector.global_detections(image)
    points = matcher.grid_detector.detect_points(image, tuple(x[0] for x in global_nodes))
    weak = matcher.grid_detector._weak_circle_points(image, points[1])
    size = detect_grid_size(points[0], image.shape[1] * points[1])
    from models.grid_geometry import GRID_SHAPES
    selected = [f for f, (c, r) in GRID_SHAPES.items()
                if size and size['rows'] == r and size['columns'] in ((9, 10) if f == 5 else (c,))]
    def match_floor(f):
        return matcher._match_floor(image, f, global_nodes, points, weak)
    matches = [(f, match_floor(f)) for f in selected]
    source = 'grid_size_then_template'
    if len(matches) != 1 or not matches[0][1].reliable:
        source = 'template_matching_fallback'
        matches += [(f, match_floor(f)) for f in range(1, 6) if f not in selected]
    diagnostics = {'detected_grid': size, 'matched_floors': [f for f, _ in matches],
                   'floor_source': source}
    rows = sorted(matches, key=lambda pair: pair[1].confidence, reverse=True)
    candidates = [{'floor': floor, 'template': match.template.template_id if match.template else None,
                   'score': round(match.confidence, 6), 'reliable': match.reliable}
                  for floor, match in rows]
    floor, best = rows[0]
    # Cross-floor near-ties cannot establish the floor from this image.
    if not best.reliable or (len(rows) > 1 and rows[1][1].reliable and best.confidence-rows[1][1].confidence < 0.02):
        return {'success': False, 'message': 'floor_ambiguous_or_unrecognized',
                'floor': None, 'floor_candidates': candidates, 'predictions': {}, **diagnostics}
    result = pipeline._recognize_match(image, best, requested_floor=floor)
    raw = pipeline.node_type_detector.detect(image, {k: v.center for k, v in result.mapped_nodes.items()})
    fixed = {}
    for node_id in result.template.end_node_ids:
        observed = raw.get(node_id)
        fixed[node_id] = {'resolved_type': '险路尽头', 'basis': 'fixed_template',
                          'visible_type': observed.node_type if observed else None}
    return {'success': result.success, 'message': result.message,
            'floor': floor, **diagnostics, 'floor_candidates': candidates,
            'template': result.template.template_id, 'fixed_nodes': fixed,
            'node_positions': {k: [float(x) for x in v.center] for k, v in result.mapped_nodes.items()},
            'node_types': {k: {'type': v.node_type, 'confidence': round(v.confidence, 6)} for k,v in raw.items()},
            'unknown_mystery_nodes': [x.node_id for x in result.mystery_nodes],
            'predictions': result.predictions}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--repository', required=True)
    parser.add_argument('--image', required=True)
    parser.add_argument('--output-directory')
    parser.add_argument('--font-path')
    args = parser.parse_args()
    value = recognize(args.repository, args.image)
    if value.get('success') and args.output_directory:
        from blackforest_render import render
        value.update(render(args.image, value, args.output_directory, args.font_path))
    print(json.dumps(value, ensure_ascii=False))
