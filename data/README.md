# Data

The dataset is not stored in this repository (about 67 MB zipped). Download it from NASA PDS:

**Nesvorný HCM Asteroid Families V2.0** (NASA Planetary Data System, Small Bodies Node)
https://doi.org/10.26033/5hyq-6k90

1. From the DOI page, download the bundle zip (`ast_nesvorny_families_V2_0.zip`).
2. Unzip it inside this `data/` folder.

You should end up with:

```
data/
└── ast.nesvorny.families_V2_0/
    └── data/
        ├── proper_catalog24.tab      # 2024 proper-orbit catalogue (primary data)
        └── families_2015/            # 2015 family lists (reference labels), *.tab files
```

The notebook reads from `data/ast.nesvorny.families_V2_0/data`. If you unzip somewhere else, change `DATA_DIR` in the first code cell.
