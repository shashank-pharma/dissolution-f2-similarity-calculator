"""Plain-assert tests. Run: .venv/bin/python test_f2.py"""

import pandas as pd

from f2_calculator import calc_f2, check_time_points, select_timepoints, summarize


def test_identical_profiles():
    prof = [20, 40, 60, 80, 90]
    assert abs(calc_f2(prof, prof) - 100) < 1e-9


def test_constant_difference_10():
    ref = [20, 40, 60, 80, 90]
    test = [x - 10 for x in ref]
    f2 = calc_f2(ref, test)
    # 50*log10(100/sqrt(101)) = 49.89
    assert abs(f2 - 49.9) < 0.05, f2


def test_85_rule_drops_later_points():
    times = [5, 10, 15, 20, 30]
    ref = [30, 60, 80, 88, 95]
    test = [25, 55, 78, 86, 94]
    used, dropped = select_timepoints(times, ref, test)
    assert used == [5, 10, 15, 20] and dropped == [30], (used, dropped)


def test_85_rule_never_reached_uses_all():
    times = [5, 10, 15]
    used, dropped = select_timepoints(times, [10, 20, 30], [5, 15, 25])
    assert used == times and dropped == []


def test_mismatched_time_points_rejected():
    rows = []
    for product, times in [("Reference", [5, 10, 15]), ("Test", [5, 10, 20])]:
        for t in times:
            rows.append((product, 1, t, 50.0))
    df = pd.DataFrame(rows, columns=["Product", "Unit", "Time_min", "Percent_Dissolved"])
    stats = summarize(df)
    try:
        check_time_points(stats, "Reference", "Test")
    except ValueError:
        return
    raise AssertionError("mismatched time points were not rejected")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in tests:
        fn()
        print(f"PASS  {fn.__name__}")
    print(f"\nAll {len(tests)} tests passed.")
