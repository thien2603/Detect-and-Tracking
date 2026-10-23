import math


def point_in_polygon(point, polygon):
    """Ray casting; points on the polygon boundary count as inside."""
    x, y = point
    inside = False
    for i, (ax, ay) in enumerate(polygon):
        bx, by = polygon[(i + 1) % len(polygon)]
        cross = (x - ax) * (by - ay) - (y - ay) * (bx - ax)
        if (
            abs(cross) < 1e-7
            and min(ax, bx) <= x <= max(ax, bx)
            and min(ay, by) <= y <= max(ay, by)
        ):
            return True
        if (ay > y) != (by > y) and x < (bx - ax) * (y - ay) / (by - ay) + ax:
            inside = not inside
    return inside


def signed_distance(point, start, end):
    dx, dy = end[0] - start[0], end[1] - start[1]
    return (dx * (point[1] - start[1]) - dy * (point[0] - start[0])) / math.hypot(dx, dy)


def crossing_within_segment(a, b, start, end):
    """Only accept crossings whose intersection lies on the finite counting segment."""
    da, db = signed_distance(a, start, end), signed_distance(b, start, end)
    if da == db:
        return False
    fraction = da / (da - db)
    if not 0 <= fraction <= 1:
        return False
    x = a[0] + fraction * (b[0] - a[0])
    y = a[1] + fraction * (b[1] - a[1])
    dx, dy = end[0] - start[0], end[1] - start[1]
    projection = ((x - start[0]) * dx + (y - start[1]) * dy) / (dx * dx + dy * dy)
    return 0 <= projection <= 1
