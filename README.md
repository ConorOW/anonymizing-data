# MRI Data Anonymisation & QC Toolkit

A set of Python scripts for anonymising neuroimaging datasets and visually quality-checking brain scans in a web browser. Claude Code generated.

---

## Scripts

### 1. `anonymize.py` — File Path Anonymisation

Reads a metadata spreadsheet (CSV or Excel) containing file paths relating to MRI data (niftis or json metadata), detects patient names embedded in those paths, and replaces them with subject IDs. Optionally renames the files and folders on disk.

**Expected path structure:**
```
.../subject_ID/PatientName-YYYY.MM.DD/PatientName-YYYY.MM.DD_scaninfo.nii
```
**After anonymisation:**
```
.../subject_ID/subject_ID-YYYY.MM.DD/subject_ID-YYYY.MM.DD_scaninfo.nii
```

**Usage:**
```bash
python anonymize.py
```

The script will prompt you to:
1. Provide the path to your metadata file (`.csv` or `.xlsx`)
2. Select which column contains the subject IDs
3. Select which columns contain file paths to anonymise
4. Choose between a **dry run** (preview only) or a **live run** (rename files on disk)

**Output:** An annotated Excel file (`anonymized_metadata.xlsx`) saved in the parent directory (one level above `scripts/`), containing the original paths, anonymised paths, and the `mv` shell command for each rename.

> **Note:** This script expects to be run from a `scripts/` subfolder. Input metadata files should be placed in the parent directory (one level above `scripts/`). When prompted for a file path, use `../filename.csv` or `../filename.xlsx` to point to the parent directory.

**Key settings** (edit at the top of the script):
| Variable | Default | Description |
|---|---|---|
| `DRY_RUN` | `True` | Set to `False` to actually rename files |
| `INCLUDE_ORIGINAL` | `True` | Include original paths in the output file |

---

### 2. `qc_report.py` — Visual QC Report Generator

Generates a self-contained HTML report for visually inspecting T1w brain scans in a web browser. For each scan, middle slices for axial, coronal, and sagittal planes are visualized alongside key acquisition metadata. Scans from the same subject are colour-grouped for easy visual comparison.

**Features:**
- Reads NIfTI (`.nii` / `.nii.gz`) and JSON sidecar paths from a spreadsheet that is fed to script
- Corrects for non-isotropic voxels so slices are not squashed
- Embeds all images directly in the HTML — no external files needed
- Groups multiple scans per subject with a shared background colour
- Shows file paths (truncated for readability, full path on hover)

**Usage:**
```bash
python qc_report.py
```

The script will prompt you to:
1. Provide the path to your metadata file (`.csv` or `.xlsx`)
2. Select which column contains the **subject ID** (used for colour grouping)
3. Select which column contains the **NIfTI paths**
4. Select which column contains the **JSON sidecar paths**

**Output:** `qc_report.html` — open in any web browser.

```bash
open qc_report.html
```

**Metadata displayed per scan:**

| Field | Source |
|---|---|
| Dimensions (voxels) | NIfTI header |
| Voxel Size (mm) | NIfTI header |
| NIfTI / JSON paths | Input spreadsheet |
| Slice Thickness | JSON sidecar |
| Manufacturer & Model | JSON sidecar |
| Field Strength | JSON sidecar |
| Series / Protocol Name | JSON sidecar |

**Dependencies:**
```bash
pip install nibabel numpy Pillow pandas openpyxl
```

---

### 3. `check_anonymization.py` — Anonymisation Verification

Verifies that patient names have been successfully removed from anonymised file paths. Loads the output Excel file from `anonymize.py`, extracts the patient name from each original path using the same `Name-YYYY.MM.DD` pattern, and confirms it is absent from the corresponding anonymised path. Results are written back to the Excel file as a `_check_status` column per checked path column.

**Usage:**
```bash
python check_anonymization.py
```

The script will prompt you to:
1. Provide the path to your anonymised metadata file (`.xlsx`)
2. Select which column contains the subject IDs
3. Select which columns contain the original file paths to check

**Output:** The input `.xlsx` file is updated in-place with a `<col>_check_status` column added for each checked column, containing `pass` or `fail` per row. A summary is also printed to the terminal.

> **Note:** Both scripts expect to be run from a `scripts/` subfolder. Input metadata files and output `.xlsx` files should be placed in the parent directory (one level above `scripts/`). When prompted for a file path, use `../filename.xlsx` to point to the parent directory.

---

### 4. (Additional) `create_mock_files.py` — Test Dataset Generator

This is a script that ca be used to create mock files and experiment with the file anoymization script - if you are feeling nervy. It creates empty placeholder NIfTI files at the paths listed in `metadata-example.csv`. Run this once to set up a test dataset before running `anonymize.py`, without needing real scan data.

**Usage:**
```bash
python create_mock_files.py
```

Reads `metadata-example.csv` from the same folder and creates empty files at every path listed in the `nifti_path` column, including any intermediate folders.

---

## Requirements

- Python 3.8+
- [nibabel](https://nipy.org/nibabel/) — reading NIfTI brain scan files
- [numpy](https://numpy.org/) — array operations on image data
- [Pillow](https://pillow.readthedocs.io/) — image processing and PNG export
- [pandas](https://pandas.pydata.org/) — reading CSV / Excel spreadsheets
- [openpyxl](https://openpyxl.readthedocs.io/) — Excel file support for pandas

Install all dependencies:
```bash
pip install nibabel numpy Pillow pandas openpyxl
```

---

## Typical Workflow

```
1. create_mock_files.py      →   IF NEEDED: set up a test dataset from metadata-example.csv for experimentation
2. anonymize.py              →   replace patient names in file paths with subject IDs
3. check_anonymization.py    →   verify no patient names remain in the anonymised paths
4. qc_report.py              →   visually inspect scans before sharing the dataset
```
