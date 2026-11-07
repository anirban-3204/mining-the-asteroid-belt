"""Build the clean asteroid dataset used in the analysis.

Reproduces the Extract and Transform steps of asteroid_families_dmw.ipynb (sections 1-2):

1. Load the 2024 proper-orbit catalogue (primary data).
2. Load the 2015 family lists (reference labels). An asteroid listed in two
   families keeps the larger family's label, so nested sub-families merge into
   their parents.
3. Clean: numbered asteroids only, numbers up to the highest labelled one,
   main belt (2.0 < a < 3.3 AU), valid H.
4. LEFT JOIN the labels onto the catalogue. Asteroids with no label are
   unassigned (fam_id = -1, fam_name = "Unassigned").
5. Add derived attributes: incl_deg, zone, a_bin, incl_class, size_class.

Usage:
    python preprocess.py
    python preprocess.py --data-dir path/to/ast.nesvorny.families_V2_0/data --out data/clean.csv
"""

import argparse
import glob
import os
import sys

import numpy as np
import pandas as pd

DEFAULT_DATA_DIR = os.path.join("data", "ast.nesvorny.families_V2_0", "data")
DEFAULT_OUT = os.path.join("data", "clean.parquet")

CATALOG_COLS = ["a", "a_err", "e", "e_err", "sini", "sini_err", "g", "s", "H", "n_opp", "packed", "name"]


def load_catalog(data_dir):
    """2024 proper-orbit catalogue: one row per asteroid."""
    path = os.path.join(data_dir, "proper_catalog24.tab")
    return pd.read_csv(path, sep=r"\s+", header=None, names=CATALOG_COLS,
                       dtype={"packed": str, "name": str})


def load_labels(data_dir):
    """2015 family lists. Returns (all label rows, one label per asteroid)."""
    rows = []
    for f in sorted(glob.glob(os.path.join(data_dir, "families_2015", "*.tab"))):
        with open(f) as fh:
            for line in fh:
                p = line.split(None, 7)
                if p:
                    rows.append((int(p[0]), int(p[6]), p[7].strip()))
    members = pd.DataFrame(rows, columns=["number", "fam_id", "fam_name"])
    if members.empty:
        raise FileNotFoundError(f"No family files found in {os.path.join(data_dir, 'families_2015')}")

    # keep-larger rule: sort by family size (largest first), keep the first label per asteroid
    fam_size = members.fam_id.value_counts()
    labels = (members.assign(size=members.fam_id.map(fam_size))
                     .sort_values(["size", "fam_id"], ascending=[False, True])
                     .drop_duplicates("number").drop(columns="size"))
    return members, labels


def clean(catalog, max_labelled):
    """Apply the cleaning filters and return (cleaned frame, row-count log)."""
    log = [("Raw 2024 catalogue", len(catalog))]

    df = catalog.assign(number=pd.to_numeric(catalog["name"], errors="coerce"))
    df = df[df.number.notna()]
    log.append(("Numbered asteroids only", len(df)))

    df = df[df.number <= max_labelled]
    log.append((f"Number <= {max_labelled:,} (2015 label population)", len(df)))

    df = df[(df.a > 2.0) & (df.a < 3.3)]
    log.append(("Main belt, 2.0 < a < 3.3 AU", len(df)))

    df = df[df.H < 30]                      # H = 99.99 means unknown
    log.append(("Valid absolute magnitude H", len(df)))

    df = df.copy()
    df["number"] = df.number.astype(int)
    return df, log


def join_labels(df, labels):
    """LEFT JOIN: every catalogue asteroid is kept; unlabelled ones become unassigned."""
    df = df.merge(labels, on="number", how="left")
    df["fam_id"] = df.fam_id.fillna(-1).astype(int)
    df["fam_name"] = df.fam_name.fillna("Unassigned")
    return df


def add_features(df):
    """Derived attributes used as warehouse dimensions and rule items."""
    df["incl_deg"] = np.degrees(np.arcsin(df.sini))
    df["zone"] = pd.cut(df.a, [2.0, 2.5, 2.82, 3.3], labels=["inner", "middle", "outer"]).astype(str)
    df["a_bin"] = (np.floor((df.a - 2.0) / 0.02) * 0.02 + 2.0).round(2)          # 0.02 AU bins
    # right-closed intervals: low = (0, 5] deg, moderate = (5, 15], high = (15, 90]
    df["incl_class"] = pd.cut(df.incl_deg, [0, 5, 15, 90], labels=["low", "moderate", "high"]).astype(str)
    # H is only a size proxy: large = H <= 13, medium = (13, 16], small = H > 16
    df["size_class"] = pd.cut(df.H, [0, 13, 16, 30], labels=["large", "medium", "small"]).astype(str)
    assert df.groupby("a_bin").zone.nunique().max() == 1, "a distance bin spans two zones"
    return df


def build(data_dir, verbose=True):
    """Run the full preprocessing and return the clean DataFrame."""
    say = print if verbose else (lambda *a, **k: None)

    catalog = load_catalog(data_dir)
    members, labels = load_labels(data_dir)
    say(f"Catalogue: {len(catalog):,} asteroids | label rows: {len(members):,} | "
        f"unique labelled asteroids: {len(labels):,} ({members.number.duplicated().sum():,} listed twice)")

    df, log = clean(catalog, labels.number.max())
    df = join_labels(df, labels)
    df = add_features(df)

    say("\nCleaning")
    for step, n in log:
        say(f"  {step:<45} {n:>10,}")

    in_catalog = labels.number.isin(pd.to_numeric(catalog["name"], errors="coerce"))
    in_final = labels.number.isin(df.number)
    say("\nLEFT JOIN")
    say(f"  labelled, not in the 2024 catalogue          {int((~in_catalog).sum()):>10,}")
    say(f"  labelled, removed by the filters             {int((in_catalog & ~in_final).sum()):>10,}")
    say(f"  labelled, matched into the final data        {int(in_final.sum()):>10,}")
    say(f"  unassigned (no 2015 label, fam_id = -1)      {int((df.fam_id < 0).sum()):>10,}")

    n_lists = members.fam_id.nunique()
    n_merged = labels.fam_id.nunique()
    n_final = df.loc[df.fam_id >= 0, "fam_id"].nunique()
    say(f"\nFamilies: {n_lists} lists -> {n_merged} after merging {n_lists - n_merged} sub-families "
        f"-> {n_final} with members in the final data")
    say(f"Final: {len(df):,} asteroids | {(df.fam_id >= 0).mean():.1%} family members | "
        f"{df.a_bin.nunique()} distance bins")
    return df


def main(argv=None):
    ap = argparse.ArgumentParser(description="Build the clean asteroid-family dataset.")
    ap.add_argument("--data-dir", default=DEFAULT_DATA_DIR,
                    help=f"folder with proper_catalog24.tab and families_2015/ (default: {DEFAULT_DATA_DIR})")
    ap.add_argument("--out", default=DEFAULT_OUT,
                    help=f"output file, .parquet or .csv (default: {DEFAULT_OUT})")
    ap.add_argument("-q", "--quiet", action="store_true", help="only print the output path")
    args = ap.parse_args(argv)

    if not os.path.exists(os.path.join(args.data_dir, "proper_catalog24.tab")):
        sys.exit(f"proper_catalog24.tab not found in {args.data_dir}. See data/README.md for the download.")

    df = build(args.data_dir, verbose=not args.quiet)

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    if args.out.endswith(".csv"):
        df.to_csv(args.out, index=False)
    else:
        df.to_parquet(args.out, index=False)
    print(f"\nWrote {len(df):,} rows x {df.shape[1]} columns to {args.out}")


if __name__ == "__main__":
    main()
