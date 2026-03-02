"""
Visual QC Report Generator
==========================
Reads a CSV or Excel file containing NIfTI and JSON sidecar paths, extracts
axial/coronal/sagittal middle slices, reads scan metadata from the JSON sidecar,
writes a self-contained HTML report for visual quality control in a browser.

Usage:
    python qc_report.py

The script will prompt for:
    - Path to the metadata file (.csv or .xlsx)
    - Which column contains subject IDs  (for colour-grouping cards)
    - Which column contains NIfTI paths
    - Which column contains JSON sidecar paths
"""

import glob
import json
import base64
import readline
from io import BytesIO
from pathlib import Path
import pandas as pd
import nibabel as nib
import numpy as np
from PIL import Image


# ---------------------------------------------------------------------------
# Configuration — metadata fields to display in the report
# ---------------------------------------------------------------------------

# Dictionary mapping the raw key name in the JSON sidecar file
# to the human-readable label that will appear in the HTML report.
METADATA_FIELDS = {
    # Acquisition parameters
    'SliceThickness':          'Slice Thickness (mm)',

    # Scanner hardware info
    'Manufacturer':            'Manufacturer',
    'ManufacturersModelName':  'Model',
    'MagneticFieldStrength':   'Field Strength (T)',

    # Scan protocol info
    'SeriesDescription':       'Series Description',
    'ProtocolName':            'Protocol Name',
}

# Five pairs of background colours (card background, header background) used to
# visually group scans that belong to the same subject.
# The script cycles through these — subject 1 gets blue, subject 2 gets green, etc.
CARD_COLORS = [
    ('#1c2535', '#202c3f'),  # blue
    ('#1c2820', '#20302a'),  # green
    ('#241c30', '#2c2040'),  # purple
    ('#2a2418', '#32291e'),  # amber
    ('#2a1c1c', '#321e1e'),  # red
]

# The folder that contains this script — used to save the output HTML file
# in the same place as the script, regardless of where the user runs it from
HERE = Path(__file__).parent

# ---------------------------------------------------------------------------
# NIfTI processing
# ---------------------------------------------------------------------------

def normalize_slice(arr):
    """Scale a 2D image slice to standard 0–255 brightness for display.

    This function stretches the brightness so the brain tissue fills the full range of greys.

    We ignore the darkest 1% and brightest 1% of non-zero voxels to avoid
    bright spots (e.g. scanner artefacts) blowing out the contrast.
    """
    arr = arr.astype(float)                      # convert integers to decimals so maths works cleanly

    nonzero = arr[arr > 0]                       # collect only voxels that aren't empty background
    if nonzero.size == 0:                        # if the whole slice is empty (blank scan)
        return np.zeros_like(arr, dtype=np.uint8)    # return a completely black image

    lo, hi = np.percentile(nonzero, 1), np.percentile(nonzero, 99)  # find the 1st and 99th brightness percentiles
    if hi == lo:                                 # if all voxels have the same value, nothing to stretch
        return np.zeros_like(arr, dtype=np.uint8)

    arr = np.clip(arr, lo, hi)                   # clamp values outside the range to the boundary values
    arr = (arr - lo) / (hi - lo) * 255           # stretch the range so lo→0 and hi→255
    return arr.astype(np.uint8)                  # convert back to whole numbers (0–255)


def slice_to_b64(slice_2d, zoom_row, zoom_col):
    """Convert a 2D brain slice into a base64-encoded PNG image string.

    Brain scans often have rectangular voxels (e.g. 1mm wide but 2mm tall).
    If we don't correct for this, slices look squashed. This function resizes
    the image so each pixel represents a physically square region in space.

    zoom_row / zoom_col are the voxel sizes in mm along each axis of the slice.
    The final image is scaled so its longest physical side is 300 pixels.

    Base64 encoding turns the PNG image into a text string that can be pasted
    directly into the HTML file — no separate image files needed.
    """
    arr = normalize_slice(slice_2d)              # scale brightness to 0–255

    h, w = arr.shape                             # height and width of the slice in pixels

    phys_w = w * zoom_col                        # physical width of the slice in millimetres
    phys_h = h * zoom_row                        # physical height of the slice in millimetres

    # Work out how much to scale the image so the longest side becomes 300px
    scale = 300.0 / max(phys_w, phys_h)
    new_w = max(1, round(phys_w * scale))        # new width in pixels (at least 1 to avoid empty image)
    new_h = max(1, round(phys_h * scale))        # new height in pixels

    img = Image.fromarray(arr, mode='L')         # create a greyscale PIL image from the numpy array
    img = img.resize((new_w, new_h), Image.LANCZOS)  # resize using high-quality downsampling
    buf = BytesIO()                              # create an in-memory buffer to hold the image data
    img.save(buf, format='PNG')                  # save the image into that buffer as a PNG
    return base64.b64encode(buf.getvalue()).decode('utf-8')  # encode the bytes as a text string


def process_nifti(nii_path):
    """Load a NIfTI brain scan and extract three middle slices for display.

    Brain scans are 3D volumes. To show them in a 2D report we take one slice
    from the middle of each anatomical plane:
        - Axial:    horizontal cross-section (looking down from above)
        - Coronal:  front-to-back cross-section (looking from the front)
        - Sagittal: left-to-right cross-section (looking from the side)

    Returns a dictionary with:
        axial, coronal, sagittal  — base64 PNG strings ready to embed in HTML
        shape                     — number of voxels in each direction (x, y, z)
        zooms                     — physical size of each voxel in mm (x, y, z)
    """
    img = nib.load(nii_path)                     # load the .nii.gz file from disk
    data = img.get_fdata()                       # read the raw voxel values into a 3D numpy array
    zooms = img.header.get_zooms()               # read the voxel dimensions (mm) from the file header
    shape = data.shape[:3]                       # get the number of voxels along x, y, z
    dx, dy, dz = float(zooms[0]), float(zooms[1]), float(zooms[2])  # voxel sizes in mm for each axis

    x_mid, y_mid, z_mid = (s // 2 for s in shape)  # find the middle index along each axis

    # Extract the middle slice for each plane and rotate 90° counter-clockwise
    # so the brain appears upright (as expected by convention).
    #
    # After rotating, the row and column axes swap — so we have to pass the
    # correct voxel size for each axis when converting to an image:
    #
    #   Slice                Before rotation       After rotation
    #   ─────────────────────────────────────────────────────────
    #   axial    [:,:,z]     rows=x(dx), cols=y(dy)  rows=y(dy), cols=x(dx)
    #   coronal  [:,y,:]     rows=x(dx), cols=z(dz)  rows=z(dz), cols=x(dx)
    #   sagittal [x,:,:]     rows=y(dy), cols=z(dz)  rows=z(dz), cols=y(dy)

    axial    = np.rot90(data[:, :, z_mid])       # horizontal slice through the middle of the brain
    coronal  = np.rot90(data[:, y_mid, :])       # front-to-back slice through the middle
    sagittal = np.rot90(data[x_mid, :, :])       # left-to-right slice through the middle

    return {
        'axial':    slice_to_b64(axial,    zoom_row=dy, zoom_col=dx),   # convert each slice to a PNG string
        'coronal':  slice_to_b64(coronal,  zoom_row=dz, zoom_col=dx),
        'sagittal': slice_to_b64(sagittal, zoom_row=dz, zoom_col=dy),
        'shape':    shape,                                               # store voxel dimensions
        'zooms':    tuple(round(float(z), 4) for z in zooms[:3]),        # store voxel sizes, rounded to 4 decimals
    }


# ---------------------------------------------------------------------------
# Metadata loading
# ---------------------------------------------------------------------------

def load_scan_metadata(json_path):
    """Read selected scan parameters from a BIDS JSON sidecar file.

    BIDS datasets store scan acquisition details in a JSON file alongside each
    NIfTI image. This function reads only the fields listed in METADATA_FIELDS
    and returns them with human-readable labels.

    If the JSON file doesn't exist, or a field is missing, 'N/A' is shown.
    """
    if not json_path.exists():                   # if there is no JSON file for this scan
        return {label: 'N/A' for label in METADATA_FIELDS.values()}  # return all fields as N/A

    with open(json_path) as f:                   # open and read the JSON file
        raw = json.load(f)                       # parse the JSON text into a Python dictionary

    # For each field we want to display, look it up in the raw JSON.
    # If the key isn't present, fall back to 'N/A'.
    return {
        label: str(raw.get(key, 'N/A'))
        for key, label in METADATA_FIELDS.items()
    }


# ---------------------------------------------------------------------------
# HTML rendering
# ---------------------------------------------------------------------------

def truncate_path(path, n_parts=3):
    """Shorten a long file path for display by keeping only the last few folders.

    For example:
        /very/long/path/to/subject/anat/sub-001_T1w.nii.gz
        becomes:
        .../anat/sub-001_T1w.nii.gz

    The full path is still shown as a tooltip when you hover over it in the report.
    n_parts controls how many folder levels to keep (default: 3).
    """
    parts = Path(path).parts                     # split the path into its individual folder/file components
    if len(parts) <= n_parts:                    # if the path is already short enough, show it as-is
        return str(path)
    return '...' + str(Path(*parts[-n_parts:]))  # otherwise, join the last n_parts components with '...' prefix


def render_card(sub_id, nii_info, metadata, color_idx=0, nii_path=None, json_path=None):
    """Build the HTML block for a single scan (one card in the report).

    Each card shows:
        - The scan label (filename stem) as a coloured header
        - Three brain slice images (axial, coronal, sagittal) side by side
        - A metadata table with image dimensions, voxel size, file paths,
          and key acquisition parameters from the JSON sidecar

    color_idx picks which background tint to use from CARD_COLORS, allowing
    all scans from the same subject to share a common colour.
    """
    card_bg, header_bg = CARD_COLORS[color_idx % len(CARD_COLORS)]  # pick colour pair, wrapping around if needed

    shape = nii_info['shape']                    # unpack image dimensions (number of voxels)
    zooms = nii_info['zooms']                    # unpack voxel sizes in mm

    # Build the rows of the metadata table that come from the NIfTI header
    # (dimensions, voxel size) and from our input spreadsheet (file paths).
    nifti_rows = f"""
        <tr>
          <td class="meta-key">Dimensions (vox)</td>
          <td class="meta-val">{shape[0]} &times; {shape[1]} &times; {shape[2]}</td>
        </tr>
        <tr>
          <td class="meta-key">Voxel Size (mm)</td>
          <td class="meta-val">{zooms[0]} &times; {zooms[1]} &times; {zooms[2]}</td>
        </tr>
        <tr>
          <td class="meta-key">NIfTI Path</td>
          <td class="meta-val meta-path" title="{nii_path or ''}">{truncate_path(nii_path) if nii_path else ''}</td>
        </tr>
        <tr>
          <td class="meta-key">JSON Path</td>
          <td class="meta-val meta-path" title="{json_path or ''}">{truncate_path(json_path) if json_path else ''}</td>
        </tr>"""

    # Build the rows from the JSON sidecar (SliceThickness, Manufacturer, etc.)
    meta_rows = ''.join(
        f"""
        <tr>
          <td class="meta-key">{label}</td>
          <td class="meta-val">{value}</td>
        </tr>"""
        for label, value in metadata.items()     # one row per metadata field
    )

    # Build the three brain slice images as HTML <figure> elements
    slices_html = ''.join(
        f"""
        <figure>
          <img src="data:image/png;base64,{nii_info[plane]}" alt="{plane.capitalize()}">
          <figcaption>{plane.capitalize()}</figcaption>
        </figure>"""
        for plane in ('axial', 'coronal', 'sagittal')  # loop over the three anatomical planes
    )

    # Assemble the full card HTML, applying the subject colour via inline styles
    return f"""
    <section class="subject-card" style="background:{card_bg}">
      <h2 class="sub-id" style="background:{header_bg}">{sub_id}</h2>
      <div class="card-body">
        <div class="slices">{slices_html}</div>
        <div class="metadata">
          <table>
            <thead><tr><th colspan="2">Scan Info</th></tr></thead>
            <tbody>{nifti_rows}{meta_rows}</tbody>
          </table>
        </div>
      </div>
    </section>"""


def generate_html(subjects):
    """Wrap all subject cards in a complete, self-contained HTML page.

    The page uses an embedded stylesheet (no external files needed) so the
    report can be shared as a single .html file and opened in any browser.
    All images are embedded as base64 strings — no separate image files.
    """
    # Concatenate every subject card into one long string of HTML
    cards = ''.join(s['card'] for s in subjects)

    # Return the full HTML document as a string
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>T1w QC Report</title>
  <style>
    /* Reset default browser margins/padding and use border-box sizing everywhere */
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}

    /* Dark background for the whole page, light text */
    body {{ font-family: 'Helvetica Neue', Arial, sans-serif; background: #1a1a1a; color: #e0e0e0; }}

    /* ── Subject cards ── */

    /* Stack cards vertically with a gap between them */
    main {{ padding: 24px; display: flex; flex-direction: column; gap: 20px; }}

    /* Each card has a dark rounded box; background colour is set per-subject via inline style */
    .subject-card {{
      background: #222; border: 1px solid #333; border-radius: 8px; overflow: hidden;
    }}

    /* Card header bar showing the scan label; background set per-subject via inline style */
    .sub-id {{
      padding: 10px 20px; font-size: 1rem; font-weight: 600;
      background: #2a2a2a; border-bottom: 1px solid #333; color: #7bb3f0;
    }}

    /* Card body: slices on the left, metadata table on the right; wraps on narrow screens */
    .card-body {{ display: flex; flex-wrap: wrap; }}

    /* ── Brain slices ── */

    /* Container for the three slice images; flex row, wraps if screen is narrow */
    .slices {{
      display: flex; flex-wrap: wrap; gap: 12px;
      padding: 16px; flex: 1; min-width: 0; align-items: flex-start;
    }}

    /* Each figure holds one image and its label beneath it */
    figure {{ display: flex; flex-direction: column; align-items: center; gap: 6px; }}

    /* Limit image size; black background for letterboxing; pixelated rendering
       prevents blurring of the brain image when the browser scales it */
    figure img {{
      max-width: 300px;
      background: #000; display: block; border-radius: 4px;
      image-rendering: pixelated;
    }}

    /* Small uppercase label under each slice (AXIAL, CORONAL, SAGITTAL) */
    figcaption {{
      font-size: 0.72rem; color: #888;
      text-transform: uppercase; letter-spacing: 0.06em;
    }}

    /* ── Metadata table ── */

    /* Metadata panel sits to the right of the slices, separated by a vertical line */
    .metadata {{
      min-width: 270px; padding: 16px; border-left: 1px solid #333;
    }}

    /* Table fills the metadata panel; no gaps between cell borders */
    table {{ width: 100%; border-collapse: collapse; font-size: 0.82rem; }}

    /* "Scan Info" header row in the table */
    thead th {{
      text-align: left; padding: 6px 8px; color: #aaa;
      font-size: 0.72rem; font-weight: 600;
      text-transform: uppercase; letter-spacing: 0.06em;
      border-bottom: 1px solid #333;
    }}

    /* Left column: the field name (greyed out) */
    .meta-key {{ color: #999; padding: 5px 8px; vertical-align: top; white-space: nowrap; }}

    /* Right column: the field value */
    .meta-val {{ color: #e0e0e0; padding: 5px 8px; word-break: break-word; }}

    /* File path rows: monospace font, slightly dimmer, wraps on long paths */
    .meta-path {{ font-family: monospace; font-size: 0.75rem; color: #aaa; word-break: break-all; }}

    /* Highlight a row when you hover over it */
    tr:hover td {{ background: #2a2a2a; }}
  </style>
</head>
<body>
  <main>{cards}</main>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Interactive input helpers
# ---------------------------------------------------------------------------

def _setup_tab_completion():
    """Enable Tab key file-path completion when the script asks for input.

    Without this, pressing Tab while typing a file path would do nothing.
    This registers a custom completer with the readline library so Tab
    expands partial paths, just like in a normal terminal.
    """
    def path_completer(text, state):
        matches = glob.glob(text + '*')                         # find all files/folders starting with what was typed
        matches = [m + '/' if Path(m).is_dir() else m for m in matches]  # add '/' to folders
        return matches[state] if state < len(matches) else None  # readline calls this repeatedly; return None when done

    readline.set_completer(path_completer)       # register our completer function
    readline.parse_and_bind('tab: complete')     # bind the Tab key to trigger completion


def prompt_input_file():
    """Ask the user for a metadata file path and keep asking until a valid one is given.

    Accepts .csv, .xlsx, and .xls files. Tab-completion is available.
    """
    while True:
        raw = input('Enter path to metadata file (CSV or XLSX): ').strip()  # ask user to type a path
        path = Path(raw)
        if not path.exists():                    # check the file actually exists
            print(f'  File not found: {path}')
        elif path.suffix not in ('.csv', '.xlsx', '.xls'):   # check it's a supported format
            print(f'  Unsupported format "{path.suffix}" — please provide a .csv or .xlsx file.')
        else:
            return path                          # valid file — return it and stop asking


def prompt_column_choice(columns, prompt):
    """Show a numbered list of column names and return whichever the user selects.

    Keeps re-prompting until the user enters a valid number.
    """
    print(f'\n{prompt}')
    for i, col in enumerate(columns):           # print each column with its number
        print(f'  [{i}] {col}')
    while True:
        raw = input('Enter number: ').strip()
        if raw.isdigit() and int(raw) < len(columns):   # check it's a valid index
            return columns[int(raw)]             # return the column name at that index
        print(f'  Please enter a number between 0 and {len(columns) - 1}.')


def load_metadata(path):
    """Load a CSV or Excel spreadsheet into a pandas DataFrame.

    A DataFrame is a table with named columns that we can loop over row by row.
    """
    path = Path(path)
    if path.suffix in ('.xlsx', '.xls'):         # Excel file
        return pd.read_excel(path)
    return pd.read_csv(path)                     # CSV file


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    _setup_tab_completion()                      # enable Tab completion before any input prompts

    # Step 1: ask the user for the spreadsheet containing the scan paths
    input_path = prompt_input_file()
    df = load_metadata(input_path)               # load it into a DataFrame
    columns = list(df.columns)                   # get the list of column names to show the user

    # Step 2: ask which columns hold the subject ID, NIfTI path, and JSON path
    id_col   = prompt_column_choice(columns, 'Which column contains the subject ID?')
    nii_col  = prompt_column_choice(columns, 'Which column contains the NIfTI paths?')
    json_col = prompt_column_choice(columns, 'Which column contains the JSON sidecar paths?')

    # Step 3: assign a background colour to each unique subject ID.
    # The first new subject gets colour 0 (blue), the second gets 1 (green), etc.
    # colour_map remembers which colour was assigned to each subject.
    color_map   = {}   # subject_id → color index
    color_count = 0    # counter that increments each time we see a new subject

    subjects = []      # will hold the rendered HTML card for each scan row

    for _, row in df.iterrows():                 # loop over every row in the spreadsheet
        nii_path  = Path(row[nii_col])           # full path to the NIfTI image
        json_path = Path(row[json_col])          # full path to the JSON sidecar
        label     = nii_path.name.replace('.nii.gz', '').replace('.nii', '')  # use filename stem as display label
        sub_id    = str(row[id_col])             # subject ID from the spreadsheet

        if sub_id not in color_map:              # if we haven't seen this subject before
            color_map[sub_id] = color_count      # assign it the next colour
            color_count += 1                     # increment the counter for the next new subject

        print(f'Processing {label}...')          # progress indicator so the user knows what's happening

        try:
            nii_info = process_nifti(nii_path)           # load the scan and extract slices
            metadata = load_scan_metadata(json_path)     # read acquisition parameters from the JSON
            card = render_card(                          # build the HTML card for this scan
                label, nii_info, metadata,
                color_idx=color_map[sub_id],             # use this subject's assigned colour
                nii_path=nii_path,
                json_path=json_path,
            )
            subjects.append({'id': label, 'card': card})  # add the card to our list
        except Exception as e:
            print(f'  ERROR processing {label}: {e}')    # if anything goes wrong, log it and move on

    if not subjects:                             # if no scans were processed successfully
        print('No subjects successfully processed.')
        return

    # Write the finished HTML report next to this script
    output_path = HERE / 'qc_report.html'
    output_path.write_text(generate_html(subjects), encoding='utf-8')  # save as UTF-8 text
    print(f'\nReport written to: {output_path.resolve()}')
    print(f'Open in browser:   open "{output_path.resolve()}"')


# Only run main() if this script is executed directly (not imported as a module)
if __name__ == '__main__':
    main()
