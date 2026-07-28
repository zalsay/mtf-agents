import unittest

import build_daily_archive


class BuildDailyArchiveTests(unittest.TestCase):
    def setUp(self):
        build_daily_archive.NAME_MAP.clear()

    def test_candidates_come_from_etf_hot_items(self):
        response = {
            "data": {
                "items": [
                    {"code": "sh510300", "name": "沪深300ETF"},
                    {"code": "159919", "name": "沪深300ETF基金"},
                    {"code": "000001", "name": "上证指数"},
                    {"code": "600000", "name": "非ETF股票"},
                ]
            }
        }

        candidates = build_daily_archive.get_candidates(response)

        self.assertEqual({"510300": 2, "159919": 2}, candidates)
        self.assertEqual("沪深300ETF", build_daily_archive.get_candidate_name("510300"))
        self.assertEqual("沪深300ETF基金", build_daily_archive.get_candidate_name("159919"))

    def test_candidates_reject_non_list_items(self):
        with self.assertRaises(build_daily_archive.OpenAPIError):
            build_daily_archive.get_candidates({"data": {"items": {}}})


if __name__ == "__main__":
    unittest.main()
