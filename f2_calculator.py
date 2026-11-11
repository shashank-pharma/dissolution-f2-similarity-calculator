"""f2 / f1 dissolution profile comparison calculator.

All rules come from the FDA 1997 guidance "Dissolution Testing of Immediate
Release Solid Oral Dosage Forms" (PDF in docs/). Page numbers below are the
PRINTED page numbers of that PDF.

Usage:
    .venv/bin/python f2_calculator.py data/sample_dissolution.csv --reference Reference
"""

import argparse
import os
import sys

import matplotlib

matplotlib.use("Agg")  # save to file only, no window
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

# =============================================================================
# RULES FROM THE PDF (single place for every rule)
# =============================================================================
UNITS_PER_PRODUCT = 12            # p. 9: "12 units each" for test and reference
CV_LIMIT_EARLIEST_PCT = 20.0      # p. 9: CV at earlier time point (e.g. 15 min) <= 20%
CV_LIMIT_OTHER_PCT = 10.0         # p. 9: CV at other time points <= 10%
CV_MULTIVARIATE_NOTE_PCT = 15.0   # p. 9: within-batch CV > 15% -> multivariate method suggested
MULTIVARIATE_PAGES = "9-10"       # pp. 9-10: multivariate procedure (NOT implemented here)
DISSOLVED_CUTOFF_PCT = 85.0       # p. 9: only one measurement after 85% dissolution of both products
F2_SIMILAR_MIN = 50.0             # p. 9: f2 greater than 50 (50-100) generally ensures sameness
F1_SIMILAR_MAX = 15.0             # p. 9: f1 values up to 15 (0-15)
# f2 equation: p. 8.  f2 = 50 * log10( [1 + (1/n) * sum((Rt - Tt)^2)]^-0.5 * 100 )
# f1 equation: p. 8.  f1 = ( sum|Rt - Tt| / sum(Rt) ) * 100

REQUIRED_COLUMNS = ["Product", "Unit", "Time_min", "Percent_Dissolved"]
OUTPUT_DIR = "outputs"

ASSUMPTION_85 = (
    "ASSUMPTION (not defined in the PDF): the PDF says only one measurement should be "
    "considered after 85% dissolution of both products, but not which one. This tool keeps "
    "all time points up to and including the first time point where BOTH the Reference mean "
    "and the Test mean are >= 85%, and drops later points."
)


# =============================================================================
# Core functions
# =============================================================================
def load_data(path):
    """Load the long-format CSV and check columns and numeric values."""
    df = pd.read_csv(path)
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required column(s): {missing}. Found: {list(df.columns)}")
    for col in ["Time_min", "Percent_Dissolved"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
        if df[col].isna().any():
            raise ValueError(f"Column '{col}' has missing or non-numeric values.")
    return df


def check_unit_counts(df):
    """Return warning strings where units per product per time point differ from 12."""
    counts = df.groupby(["Product", "Time_min"])["Unit"].nunique()
    return [
        f"WARNING: {p} at {t:g} min has {n} units (PDF p. 9 says {UNITS_PER_PRODUCT})."
        for (p, t), n in counts.items()
        if n != UNITS_PER_PRODUCT
    ]


def summarize(df):
    """Mean, SD (sample, n-1) and %CV per product per time point."""
    g = df.groupby(["Product", "Time_min"])["Percent_Dissolved"]
    out = g.agg(Mean="mean", SD="std").reset_index()
    out["CV_pct"] = out["SD"] / out["Mean"] * 100
    return out


def get_times(stats, product):
    return sorted(stats.loc[stats["Product"] == product, "Time_min"].tolist())


def check_time_points(stats, reference, test):
    """Raise ValueError if Reference and Test do not have identical time points."""
    ref_t, test_t = get_times(stats, reference), get_times(stats, test)
    if ref_t != test_t:
        raise ValueError(
            f"Time points differ between {reference} {ref_t} and {test} {test_t}. "
            "The PDF (p. 9) requires the same time points for both profiles."
        )


def variability_table(stats, product):
    """Per-time-point CV check: earliest <= 20%, later <= 10% (p. 9)."""
    rows = stats[stats["Product"] == product].sort_values("Time_min").reset_index(drop=True)
    limits = [CV_LIMIT_EARLIEST_PCT if i == 0 else CV_LIMIT_OTHER_PCT for i in range(len(rows))]
    table = pd.DataFrame({
        "Product": product,
        "Time_min": rows["Time_min"],
        "CV_pct": rows["CV_pct"],
        "Limit_pct": limits,
    })
    table["Status"] = np.where(table["CV_pct"] <= table["Limit_pct"], "PASS", "EXCEEDS")
    return table


def select_timepoints(times, ref_means, test_means):
    """Apply the 85% rule (see ASSUMPTION_85). Returns (used, dropped)."""
    for i, (r, t) in enumerate(zip(ref_means, test_means)):
        if r >= DISSOLVED_CUTOFF_PCT and t >= DISSOLVED_CUTOFF_PCT:
            return list(times[: i + 1]), list(times[i + 1:])
    return list(times), []


def calc_f2(ref, test):
    """Similarity factor, PDF p. 8."""
    ref, test = np.asarray(ref, float), np.asarray(test, float)
    n = len(ref)
    return 50 * np.log10((1 + np.sum((ref - test) ** 2) / n) ** -0.5 * 100)


def calc_f1(ref, test):
    """Difference factor, PDF p. 8."""
    ref, test = np.asarray(ref, float), np.asarray(test, float)
    return np.sum(np.abs(ref - test)) / np.sum(ref) * 100


def verdict(f1, f2):
    """Wording follows the PDF (p. 9): 'generally' similar if f2 >= 50 and f1 in 0-15."""
    if f2 >= F2_SIMILAR_MIN and 0 <= f1 <= F1_SIMILAR_MAX:
        return "Generally taken as similar (f2 >= 50 and f1 <= 15)"
    return "Does not meet the generally used criterion (f2 >= 50 and f1 <= 15)"


# =============================================================================
# Main
# =============================================================================
def main():
    parser = argparse.ArgumentParser(description="f2/f1 dissolution profile comparison")
    parser.add_argument("csv", help="long-format CSV: Product, Unit, Time_min, Percent_Dissolved")
    parser.add_argument("--reference", required=True, help="name of the Reference product")
    args = parser.parse_args()

    try:
        df = load_data(args.csv)
        if args.reference not in set(df["Product"]):
            raise ValueError(f"Reference '{args.reference}' not found. Products: {sorted(set(df['Product']))}")

        for w in check_unit_counts(df):
            print(w)

        stats = summarize(df)
        tests = sorted(p for p in set(df["Product"]) if p != args.reference)
        if not tests:
            raise ValueError("No Test products found besides the Reference.")
        for t in tests:
            check_time_points(stats, args.reference, t)
    except ValueError as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    print("\nMean / SD / %CV per product per time point")
    print(stats.round(2).to_string(index=False))

    ref_stats = stats[stats["Product"] == args.reference].sort_values("Time_min")
    times = ref_stats["Time_min"].tolist()
    ref_means = ref_stats["Mean"].tolist()
    ref_var = variability_table(stats, args.reference)

    summary_rows = []
    any_cv_above_15 = bool((stats["CV_pct"] > CV_MULTIVARIATE_NOTE_PCT).any())

    for test in tests:
        print("\n" + "=" * 70)
        print(f"{test} vs {args.reference}")
        print("=" * 70)

        test_stats = stats[stats["Product"] == test].sort_values("Time_min")
        test_means = test_stats["Mean"].tolist()

        # Variability check (Reference and Test)
        var = pd.concat([ref_var, variability_table(stats, test)], ignore_index=True)
        print("Variability check (earliest <= 20% CV, later <= 10% CV; PDF p. 9)")
        print(var.round(2).to_string(index=False))
        var_ok = bool((var["Status"] == "PASS").all())
        var_status = "PASS" if var_ok else "EXCEEDS"

        # 85% rule
        print("\n" + ASSUMPTION_85)
        used, dropped = select_timepoints(times, ref_means, test_means)
        print(f"Time points used:    {[f'{t:g}' for t in used]}")
        print(f"Time points dropped: {[f'{t:g}' for t in dropped] if dropped else 'none'}")
        idx = [times.index(t) for t in used]
        r = [ref_means[i] for i in idx]
        t_ = [test_means[i] for i in idx]

        f2 = calc_f2(r, t_)
        f1 = calc_f1(r, t_)
        v = verdict(f1, f2)
        if not var_ok:
            v += " | variability limits EXCEEDED: the PDF's conditions for using mean data are not met"
        print(f"\nn = {len(used)}   f1 = {f1:.2f}   f2 = {f2:.2f}")
        print(f"Verdict: {v}")

        summary_rows.append({
            "Test": test, "Reference": args.reference, "n_points_used": len(used),
            "time_points_used": " ".join(f"{x:g}" for x in used),
            "time_points_dropped": " ".join(f"{x:g}" for x in dropped),
            "f1": round(f1, 2), "f2": round(f2, 2),
            "verdict": v, "variability_status": var_status,
        })

    if any_cv_above_15:
        print(
            f"\nNOTE: at least one %CV is above {CV_MULTIVARIATE_NOTE_PCT:g}%. The PDF suggests a "
            f"multivariate model-independent method in that case (printed pp. {MULTIVARIATE_PAGES}); "
            "this tool does NOT implement it."
        )

    # Save outputs
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    csv_path = os.path.join(OUTPUT_DIR, "f2_summary.csv")
    pd.DataFrame(summary_rows).to_csv(csv_path, index=False)

    plt.figure()
    for product in [args.reference] + tests:
        s = stats[stats["Product"] == product].sort_values("Time_min")
        plt.plot(s["Time_min"], s["Mean"], marker="o", label=product)
    plt.xlabel("Time (minutes)")
    plt.ylabel("Mean dissolved (%)")
    plt.legend()
    png_path = os.path.join(OUTPUT_DIR, "mean_profiles.png")
    plt.savefig(png_path, dpi=100)
    plt.close()

    print(f"\nSaved: {csv_path}\nSaved: {png_path}")


if __name__ == "__main__":
    main()
