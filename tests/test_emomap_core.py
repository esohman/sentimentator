import unittest

from sentimentator.emomap import build_schedule, geometry, parse_points


class EmoMapGeometryTests(unittest.TestCase):
    def test_origin_has_zero_radius(self):
        point = geometry(480/960, 368/720)
        self.assertAlmostEqual(point["radius"], 0.0, places=6)

    def test_raw_coordinates_are_preserved(self):
        point = geometry(0.25, 0.75)
        self.assertEqual(point["x_norm"], 0.25)
        self.assertEqual(point["y_norm"], 0.75)

    def test_invalid_point_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_points('[{"x": 1.2, "y": 0.5}]')

    def test_multiple_points_are_kept_separately(self):
        points = parse_points('[{"x":0.5,"y":0.2},{"x":0.5,"y":0.8}]')
        self.assertEqual(len(points), 2)
        self.assertNotEqual(points[0]["dy"], points[1]["dy"])


class EmoMapScheduleTests(unittest.TestCase):
    def make_items(self):
        items = []
        for group in ["a", "b", "c", "d", "e", "f", "g", "h", "i", "j"]:
            items.extend([
                {"item_key": f"{group}_iso", "target": group, "target_group": group,
                 "condition": "isolated", "prime_arm": None, "active": True},
                {"item_key": f"{group}_ctx1", "target": group, "target_group": group,
                 "condition": "context", "prime_arm": None, "active": True},
                {"item_key": f"{group}_ctx2", "target": group, "target_group": group,
                 "condition": "context", "prime_arm": None, "active": True},
            ])
        return items

    def test_main_arm_isolated_precedes_contexts(self):
        schedule = build_schedule(self.make_items(), arm="main", seed=42, min_target_lag=5)
        positions = {item["item_key"]: i for i, item in enumerate(schedule)}
        for group in ["a","b","c","d","e","f","g","h","i","j"]:
            self.assertLess(positions[f"{group}_iso"], positions[f"{group}_ctx1"])
            self.assertLess(positions[f"{group}_iso"], positions[f"{group}_ctx2"])

    def test_priming_arm_reverses_only_designated_target_sequence(self):
        items = self.make_items()
        for item in items:
            if item["item_key"] == "a_ctx1":
                item["prime_arm"] = "prime_negative"
        primed = build_schedule(items, arm="prime_negative", seed=5, min_target_lag=3)
        normal = build_schedule(items, arm="main", seed=5, min_target_lag=3)
        ppos = {item["item_key"]: i for i, item in enumerate(primed)}
        npos = {item["item_key"]: i for i, item in enumerate(normal)}
        self.assertLess(ppos["a_ctx1"], ppos["a_iso"])
        self.assertLess(npos["a_iso"], npos["a_ctx1"])


    def test_equal_length_groups_keep_requested_lag(self):
        schedule = build_schedule(self.make_items(), arm="main", seed=42, min_target_lag=5)
        last = {}
        gaps = []
        for position, item in enumerate(schedule, start=1):
            group = item["target_group"]
            if group in last:
                gaps.append(position - last[group] - 1)
            last[group] = position
        self.assertGreaterEqual(min(gaps), 5)

    def test_every_item_occurs_once(self):
        items = self.make_items()
        schedule = build_schedule(items, seed=123)
        self.assertEqual(len(schedule), len(items))
        self.assertEqual(len({i["item_key"] for i in schedule}), len(items))


if __name__ == "__main__":
    unittest.main()
