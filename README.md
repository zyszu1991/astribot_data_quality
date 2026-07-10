# Astribot Data Quality (astribot-dq)

Standalone HDF5 data quality inspection toolkit, forked and extracted from `astribot_upload_data_v2`.

## What it does

Validates HDF5 robot data files with the following checks:

- **Structure checks** – required keys presence, dimension consistency
- **Timestamp checks** – duplicates, jumps, duration validity, cross-key alignment
- **FK (Forward Kinematics) checks** – joint data vs Cartesian pose consistency
- **Frame difference checks** – joint state/velocity/command, Cartesian state/command

## Quick Start

### Installation

```bash
pip install -e .
```

### Usage

Validate a single file:

```bash
astribot-dq /path/to/episode.hdf5
```

Batch validate a directory:

```bash
astribot-dq /path/to/episodes/
```

Or via Python:

```python
from astribot_dq import HDF5Validator

validator = HDF5Validator()
validator.verify_data("/path/to/file.hdf5")
```

### Configuration

Edit `config/validation_config.yaml` to adjust thresholds and enable/disable checks.

## Related

- `scripts/log_statistics.py` – parse QC logs and generate statistical charts
- `astribot_dq/invalid_data_db.py` – SQLite-based invalid data tracking with optional Feishu alerts
- `docs/validation_strategy.md` – detailed validation strategy documentation
