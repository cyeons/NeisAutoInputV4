import unittest

from neis_v4.ui.widgets import estimated_progress


class EstimatedProgressTest(unittest.TestCase):
    def test_scales_with_elapsed_and_stops_at_95(self) -> None:
        self.assertEqual(estimated_progress(0, 60), 0)
        self.assertEqual(estimated_progress(30, 60), 50)
        self.assertEqual(estimated_progress(600, 60), 95)  # 예상보다 오래 걸려도 100%는 실제로 끝났을 때만
        self.assertEqual(estimated_progress(5, 0), 95)  # 예상 시간이 0이어도 오류 없이


if __name__ == "__main__":
    unittest.main()
