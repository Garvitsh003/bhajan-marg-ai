from scripts.daily_cloud_ingest import point_id_for


def test_point_ids_are_deterministic():
    assert point_id_for("video123", 0) == point_id_for("video123", 0)


def test_point_ids_differ_by_chunk():
    assert point_id_for("video123", 0) != point_id_for("video123", 1)


def test_point_ids_differ_by_video():
    assert point_id_for("video123", 0) != point_id_for("video456", 0)
