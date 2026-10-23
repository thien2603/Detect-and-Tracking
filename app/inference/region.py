from app.events.geometry import point_in_polygon


def filter_detections_by_region(detections, region):
    if region is None:
        return detections
    return [
        d
        for d in detections
        if point_in_polygon(((d.bbox[0] + d.bbox[2]) / 2, d.bbox[3]), region.points)
    ]
