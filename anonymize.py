"""
Filename Anonymisation
======================
Reads our metadata CSV/Excel file containing file paths to brain scans and jsons,
finds and replaces patient names in those paths with subject IDs;
writes an annotated output CSV/xlsx; If chosen, renames the file and folders on disk.

Expected path structure in the metadata file:
    .../subject_ID/PatientName-YYYY.MM.DD/PatientName-YYYY.MM.DD_scaninfo.nii

After anonymisation:
    .../subject_ID/subject_id-YYYY.MM.DD/subject_id-YYYY.MM.DD_scaninfo.nii
"""

import re                  # regular expressions — used to detect the Name-YYYY.MM.DD pattern
import glob                # file path expansion — used for tab-completion
import readline            # GNU readline — enables tab-completion in input() prompts
import pandas as pd        # Pandas for dataframe manipulation
from pathlib import Path   # Path for working with file paths


# ---------------------------------------------------------------------------
# Quick function to get Tab-completion set up
# ---------------------------------------------------------------------------

def _setup_tab_completion():
    """Enable file path tab-completion when the script prompts for input.

    Python's built-in input() has no tab-completion by default.
    Here we register a custom completer with the readline library so that
    pressing Tab expands partial file paths, just like in a normal terminal.
    """

    # Set function name and inputs
    def path_completer(text, state):

        # Expand the partial path typed by user into all matching filesystem entries
        matches = glob.glob(text + '*')

        # Append '/' to directories so Tab keeps drilling into them
        matches = [m + '/' if Path(m).is_dir() else m for m in matches]

        # readline calls this repeatedly with state=0,1,2,... until None is returned
        return matches[state] if state < len(matches) else None

    readline.set_completer(path_completer)

    # Only treat spaces as word delimiters so that path characters like '/' and '.'
    # are passed through to the completer intact — this allows '../' to work
    readline.set_completer_delims(' \t\n')

    # 'tab: complete' is the readline binding that triggers the completer on Tab
    readline.parse_and_bind('tab: complete')


# Run tab-completion setup immediately when the script is run
_setup_tab_completion()

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# DRY_RUN = True  → show what would be renamed but don't touch any files
# DRY_RUN = False → actually rename files and folders on disk
DRY_RUN = True

# INCLUDE_ORIGINAL = True  → keep the original path columns in the output CSV
#                            alongside the new anonymized columns (useful for audit)
# INCLUDE_ORIGINAL = False → drop original path columns, output only anonymized ones
INCLUDE_ORIGINAL = True


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------

def anonymize_filepath(filepath, subject_id):
    """Generate the anonymized version of a file path.

    Walks through each component of the path looking for the ID of the subject
    which is in the column that has been provided by the user via input().

    The folder immediately after subject ID is expected to be in the format
    PatientName-YYYY.MM.DD. The function extracts just the name portion
    (everything before the date), then replaces every occurrence of that
    name in the full path string with subject ID — this renames both the
    folder and the filename in one step while preserving the date.

    Example:
        /data/P1001/Marcus_Aurelius-2024.03.15/Marcus_Aurelius-2024.03.15_T1.nii
      → /data/P1001/P1001-2024.03.15/P1001-2024.03.15_T1.nii

    Returns the original filepath unchanged (with a warning) if:
      - the value is NaN / missing
      - subject ID is not found anywhere in the path
      - the folder after subject ID doesn't match the expected Name-date pattern
    """

    # Skip rows with missing path values
    if pd.isna(filepath) or str(filepath) == 'nan':
        return filepath

    # Split the path into its individual folder/file components
    # e.g. '/data/P1001/Marcus_Aurelius-2024.03.15/file.nii'
    #   →  ('/', 'data', 'P1001', 'Marcus_Aurelius-2024.03.15', 'file.nii')
    parts = Path(filepath).parts

    # Loop over each of the parts
    for i, part in enumerate(parts):

        # Find the component that matches the subject ID
        # Also ensure there is at least one more component after it
        # (i.e. it's not the filename itself)
        if part == subject_id and i + 1 < len(parts) - 1:
            name_date_field = parts[i + 1]  # e.g. 'Marcus_Aurelius-2024.03.15'

            # Match the Name-YYYY.MM.DD pattern.
            # Group 1 captures everything up to the date (the patient name).
            # Group 2 captures the date suffix including the leading dash.
            # The (.*)$ at the end allows for any trailing characters after the date.
            match = re.match(r'^(.+?)(-\d{4}\.\d{2}\.\d{2}.*)$', name_date_field)


            if match:
                name_only = match.group(1)  # e.g. 'Marcus_Aurelius'
                # Replace all occurrences of the patient name in the full path
                # including folder name and the filename.
                return filepath.replace(name_only, subject_id)

            # The folder exists but doesn't follow the expected Name-date format
            return filepath

    # subject ID was not found anywhere in the path — nothing to anonymize
    return filepath


def anonymize_columns(df, id_column, columns):
    """Add anonymized path columns and rename-command columns to the DataFrame.

    For each column in `columns`, two new columns are added:
      - <col>_anonymized  : the anonymized file path
      - <col>_rename_cmd  : the shell 'mv' command that performs the rename
                            (useful as an audit trail in the output CSV)

    Original DataFrame is not modified — a copy is returned.
    """

    # Create a copy to work with
    df = df.copy()

    # Go over columns
    for col in columns:

        # Skip if the expected column isn't present (e.g. typo in config)
        if col not in df.columns:
            continue

        anon_col = f'{col}_anonymized'  # e.g. 'nifti_path_anonymized'
        cmd_col  = f'{col}_rename_cmd'  # e.g. 'nifti_path_rename_cmd'

        # Apply anonymize_filepath to every row, passing 1) the filepath
        # and 2) the subject ID from the same row
        df[anon_col] = df.apply(
            lambda row: anonymize_filepath(str(row[col]), str(row[id_column])),
            axis=1,
        )

        # Build a shell mv command for each row so the output CSV records
        # exactly what rename was (or would be) performed (if DRY_RUN == True)
        df[cmd_col] = df.apply(
            lambda row: f'mv "{row[col]}" "{row[anon_col]}"',
            axis=1,
        )

    return df


def rename_files(df, columns, dry_run=True):
    """Rename files (and clean up empty folders) on disk.

    Iterates over every row and path column, resolving the source and
    destination paths, then either previews or performs the rename.

    After each rename the old patient-name folder is checked: if it is now
    empty (all its files have been moved out) it is deleted automatically.

    A summary DataFrame is returned recording the status of every operation:
      dry_run          — DRY_RUN=True, no files touched
      renamed          — file successfully renamed
      source_not_found — original file does not exist on disk
      no_change        — source and destination paths are identical
      target_exists    — destination already exists (skipped to avoid overwrite)
      error: <msg>     — an unexpected exception occurred
    """

    # Initialize empty list
    results = []

    # Loop over rows first so each subject is fully processed before moving on
    for idx, row in df.iterrows():

        # Then loop over each path column for this row
        for col in columns:

            # Set the name for our anonymized column
            anon_col = f'{col}_anonymized'

            src = Path(row[col])        # original file path (absolute)
            dst = Path(row[anon_col])   # anonymized file path (absolute)

            if not src.exists():
                # File missing — log and move on without crashing
                status = 'source_not_found'

            elif src == dst:
                # Path unchanged — nothing to do as no anoymization took place
                status = 'no_change'

            elif dst.exists():
                # Destination already exists — skip to avoid accidentally overwriting
                status = 'target_exists'

            elif dry_run:
                # Dry run — record what would happen but don't touch the filesystem
                status = 'dry_run'

            else:
                try:
                    # Create the destination folder
                    # (e.g. P1001-2024.03.15/ needs to be created before moving the file)
                    dst.parent.mkdir(parents=True, exist_ok=True)

                    # Save the source's parent folder before renaming
                    # so we can check whether to delete it afterward
                    old_parent = src.parent

                    # Perform the rename/move
                    src.rename(dst)

                    # If the old name folder is now empty, remove it.
                    # old_parent != dst.parent prevents deleting a folder that is also the destination.
                    if old_parent != dst.parent and not any(old_parent.iterdir()):
                        old_parent.rmdir()

                    status = 'renamed'

                except Exception as e:
                    status = f'error: {str(e)}'

            # Record the outcome for every row so we can summarise at the end
            results.append({
                'row': idx,
                'column': col,
                'original': str(src),
                'anonymized': str(dst),
                'status': status,
            })

    return pd.DataFrame(results)


def extract_patient_name(filepath, subject_id):
    """Return the patient name found in filepath, or None if not extractable.

    Uses the same Name-YYYY.MM.DD pattern as anonymize_filepath so we are
    checking for exactly what was replaced during anonymization.
    """

    # Split the file path into its individual folder/file components
    parts = Path(str(filepath)).parts

    # Walk through each component looking for the subject ID folder
    for i, part in enumerate(parts):

        # When we find the subject ID folder, the next folder should contain the patient name
        if part == subject_id and i + 1 < len(parts) - 1:

            # Try to match the Name-YYYY.MM.DD pattern on the next folder
            match = re.match(r'^(.+?)(-\d{4}\.\d{2}\.\d{2}.*)$', parts[i + 1])

            if match:
                name = match.group(1)  # extract just the name portion (everything before the date)

                # Only return the name if it differs from the subject ID
                # (if they're the same the path was already anonymised)
                if name != subject_id:
                    return name

    # No patient name could be extracted from this path
    return None


def run_check(df, id_column, path_columns):
    """Check that patient names from original paths are absent in _anonymized columns.

    Adds a <col>_check_status column for each checked column with 'pass' or 'fail'
    per row, then returns the updated DataFrame.
    """

    # Keep a running list of every failure found across all columns
    failures = []

    # Loop over each original path column
    for orig_col in path_columns:

        # Build the expected names for the anonymized and status columns
        anon_col   = f'{orig_col}_anonymized'   # e.g. 'nifti_path_anonymized'
        status_col = f'{orig_col}_check_status' # e.g. 'nifti_path_check_status'

        if anon_col not in df.columns:
            print(f'\n  WARNING: No "{anon_col}" column found — skipping {orig_col}.')
            continue

        print(f'\nChecking: {orig_col} -> {anon_col}')
        col_failures = 0

        statuses = []  # will hold 'pass' or 'fail' for every row in this column

        # Go through the spreadsheet one row at a time
        for idx, row in df.iterrows():
            original   = str(row[orig_col])   # the original file path before anonymization
            anonymized = str(row[anon_col])    # the anonymized file path after anonymization
            subject_id = str(row[id_column])   # the subject ID for this row (e.g. 'P1001')

            # Try to extract the patient name from the original path
            name = extract_patient_name(original, subject_id)

            if name is not None and name in anonymized:
                # The patient name was found — anonymization failed for this row
                print(f'  FAIL row {idx}: name "{name}" still present')
                print(f'       original  : {original}')
                print(f'       anonymized: {anonymized}')
                failures.append((idx, orig_col, name, anonymized))
                col_failures += 1
                statuses.append('fail')
            else:
                # The patient name was not found in the anonymized path — all good
                statuses.append('pass')

        # Write the pass/fail results as a new column in the spreadsheet
        df[status_col] = statuses

        if col_failures == 0:
            print('  PASS — no patient names found in anonymized paths')

    # Print an overall summary
    print('\n' + '=' * 60)
    if failures:
        print(f'FAILED: {len(failures)} path(s) still contain patient names.')
    else:
        print('PASSED: All anonymized paths are free of patient names.')

    return df


def save_output(df, output_path, include_original):
    """Write the annotated DataFrame to an Excel file.

    If include_original is False, any column that has a corresponding
    *_anonymized version is dropped — only the anonymized columns are kept.
    This keeps the output tidy when the original paths are no longer needed.
    """
    if not include_original:
        # Find all the newly added anonymized columns
        anon_cols = [c for c in df.columns if c.endswith('_anonymized')]
        # Work out which original columns they replaced
        original_names = {c.replace('_anonymized', '') for c in anon_cols}
        # Keep everything except the original path columns, then append anonymized cols
        keep = [c for c in df.columns if c not in original_names] + anon_cols
        df = df[keep]

    df.to_excel(output_path, index=False, na_rep="NA")


# ---------------------------------------------------------------------------
# Interactive input helpers
# ---------------------------------------------------------------------------

def load_metadata(path):
    """Load a metadata file into a pandas DataFrame.

    Supports .csv and .xlsx/.xls formats.
    Raises FileNotFoundError if the path doesn't exist.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f'File not found: {path}')
    if path.suffix in ('.xlsx', '.xls'):
        return pd.read_excel(path)
    return pd.read_csv(path)


def prompt_output_dir():
    """Prompt the user to enter a directory to save the output Excel file.

    Keeps re-prompting until an existing directory is provided.
    Tab-completion is available.
    """
    while True:
        raw = input('Enter path to output directory for anonymized_metadata.xlsx: ').strip()
        path = Path(raw)
        if not path.exists():
            print(f'  Directory not found: {path}')
        elif not path.is_dir():
            print(f'  That path is a file, not a directory: {path}')
        else:
            return path


def prompt_input_file():
    """Prompt the user to enter the path to a metadata file.

    Keeps re-prompting until a valid, supported file is provided.
    Tab-completion is available (set up at beginning).
    """
    while True:
        raw = input('Enter path to metadata file (CSV or XLSX): ').strip()
        path = Path(raw)
        if not path.exists():
            print(f'  File not found: {path}')
        elif path.suffix not in ('.csv', '.xlsx', '.xls'):
            print(f'  Unsupported format "{path.suffix}" — please provide a .csv or .xlsx file.')
        else:
            return path


def prompt_column_choice(columns, prompt):
    """Display a numbered list of column names and return the one the user picks.

    Used for single-selection questions (e.g. which column is the subject ID).
    Re-prompts until a valid number is entered.
    """
    print(f'\n{prompt}')
    for i, col in enumerate(columns):
        print(f'  [{i}] {col}')
    while True:
        raw = input('Enter number: ').strip()
        if raw.isdigit() and int(raw) < len(columns):
            return columns[int(raw)]
        print(f'  Please enter a number between 0 and {len(columns) - 1}.')


def prompt_path_columns(columns):
    """Display a numbered list of columns and return the ones the user selects.

    Used for multi-selection (e.g. which columns contain file paths).
    The user can select multiple columns by entering space-separated numbers.
    Re-prompts until at least one valid selection is made.
    """
    print('\nWhich columns contain file paths to anonymize?')
    for i, col in enumerate(columns):
        print(f'  [{i}] {col}')
    print('Enter column numbers separated by spaces (e.g. 1 3):')
    while True:
        raw = input('> ').strip()
        indices = raw.split()
        if all(idx.isdigit() and int(idx) < len(columns) for idx in indices) and indices:
            return [columns[int(idx)] for idx in indices]
        print(f'  Please enter valid numbers between 0 and {len(columns) - 1}.')


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    # Step 1: ask the user for the input metadata file
    input_path = prompt_input_file()
    df = load_metadata(input_path)

    # Step 2: ask where to save the output Excel file
    output_dir = prompt_output_dir()
    output_file = output_dir / 'anonymized_metadata.xlsx'

    columns = list(df.columns)

    # Step 3: ask which column holds the subject IDs
    # (used to replace patient names in file paths)
    id_column = prompt_column_choice(columns, 'Which column contains the subject ID?')

    # Step 4: ask which columns contain file paths to anonymize
    path_columns = prompt_path_columns(columns)

    # Step 5: compute anonymized paths and rename commands, added as new columns
    df_anon = anonymize_columns(df, id_column, path_columns)

    # Step 6: confirm whether to do a dry run or rename for real
    print('\nRun mode:')
    print('  [0] Dry run — compute anonymized paths only, do not rename any files')
    print('  [1] Live run — rename files and folders on disk')
    while True:
        mode = input('Enter number: ').strip()
        if mode == '0':
            dry_run = True
            break
        elif mode == '1':
            dry_run = False
            break
        print('  Please enter 0 or 1.')

    if not dry_run:
        # Extra confirmation before touching any files on disk
        print(f'\nAbout to rename files for {len(df_anon)} rows across {len(path_columns)} column(s).')
        print('This cannot be undone automatically. Type YES to proceed: ', end='')
        confirm = input().strip()
        if confirm != 'YES':
            print('Aborted — no files were renamed.')
            dry_run = True  # fall back to dry run so the CSV is still saved

    # Step 7: rename (or dry-run preview) files on disk
    rename_files(df_anon, path_columns, dry_run=dry_run)

    # Step 8: verify that no patient names remain in the anonymized paths
    # adds a _check_status column for each path column to the DataFrame
    print('\n--- Anonymization Check ---')
    df_anon = run_check(df_anon, id_column, path_columns)

    # Step 9: save the annotated DataFrame (including check results) to Excel
    save_output(df_anon, output_file, include_original=INCLUDE_ORIGINAL)
    print(f'\nOutput saved to: {output_file}')


if __name__ == '__main__':
    main()
