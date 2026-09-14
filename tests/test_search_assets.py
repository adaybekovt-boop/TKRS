import unittest
from pathlib import Path

from tools.search_assets import DEFAULT_INDEX, REPO_ROOT, load_index, search_assets


class SearchAssetsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_index(DEFAULT_INDEX)
        cls.assets = cls.catalog["assets"]

    def test_catalog_count_matches_index(self):
        self.assertEqual(self.catalog["asset_count"], len(self.assets))
        self.assertGreaterEqual(len(self.assets), 410)

    def test_exact_name_ranks_first(self):
        results = search_assets(self.assets, "Tower Square Arch", limit=3)
        self.assertTrue(results)
        self.assertEqual(results[0]["id"], "arch_arches_kenney-castle_001")

    def test_known_beam_ranks_first(self):
        results = search_assets(self.assets, "Primitive Beam", limit=3)
        self.assertTrue(results)
        self.assertEqual(results[0]["id"], "arch_beams_kaykit-proto_001")

    def test_subcategory_filter(self):
        results = search_assets(self.assets, "wall", subcategory="walls", limit=20)
        self.assertTrue(results)
        self.assertTrue(all(item["subcategory"] == "walls" for item in results))

    def test_russian_alias(self):
        results = search_assets(self.assets, "арка", limit=10)
        self.assertTrue(results)
        self.assertEqual(results[0]["subcategory"], "arches")

    def test_no_match(self):
        results = search_assets(self.assets, "zzzxxyy_nonexistent_asset_term", limit=5)
        self.assertEqual(results, [])

    def test_result_paths_exist(self):
        results = search_assets(self.assets, "door", limit=10)
        self.assertTrue(results)
        for result in results:
            self.assertTrue((REPO_ROOT / result["path"]).is_dir())
            self.assertTrue(result["files"])


if __name__ == "__main__":
    unittest.main()
