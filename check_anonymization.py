"""
Anonymization Check
===================
Interactively loads the anonymized_metadata.xlsx produced by anonymize.py
and verifies that no patient names remain in the anonymized path columns.

For each original path it extracts the patient name using the same
Name-YYYY.MM.DD regex used during anonymization, then checks that name
is absent from the corresponding _anonymized column.
"""

import re        # regular expressions — used to find the Name-YYYY.MM.DD pattern in file paths
import glob      # file path expansion — used to suggest matching paths when the user presses Tab
import readline  # GNU readline — enables tab-completion when typing file paths at the prompt
from pathlib import Path  # Path — a convenient way to work with file and folder paths

import pandas as pd  # pandas — used to load and work with the Excel spreadsheet as a table


# A pattern that matches the Name-YYYY.MM.DD folder format used in the file paths.
# Group 1 captures everything before the date (the patient name).
# Group 2 captures the date and anything after it.
# This is the same pattern used in anonymize.py, so we're checking for exactly what was replaced.
NAME_DATE_RE = re.compile(r'^(.+?)(-\d{4}\.\d{2}\.\d{2}.*)$')


# ---------------------------------------------------------------------------
# Tab completion (same as anonymize.py)
# ---------------------------------------------------------------------------

def _setup_tab_completion():
    # When the user is typing a file path at a prompt, pressing Tab will suggest
    # matching files and folders — just like in a normal terminal.
    def path_completer(text, state):
        # Find all files and folders that start with whatever the user has typed so far
        matches = glob.glob(text + '*')

        # Add a trailing slash to folders so Tab keeps drilling into them
        matches = [m + '/' if Path(m).is_dir() else m for m in matches]

        # readline calls this repeatedly with state=0,1,2,... to cycle through suggestions
        return matches[state] if state < len(matches) else None

    # Register our custom completer function with readline
    readline.set_completer(path_completer)

    # Tell readline to trigger the completer when the user presses Tab
    readline.parse_and_bind('tab: complete')


# Run tab-completion setup as soon as the script starts
_setup_tab_completion()


# ---------------------------------------------------------------------------
# Interactive input helpers
# ---------------------------------------------------------------------------

def prompt_input_file():
    """Prompt for the anonymized metadata xlsx until a valid file is given."""

    # Keep asking until the user provides a file that exists and is the right format
    while True:
        raw = input('Enter path to anonymized metadata file (XLSX): ').strip()  # ask the user to type a file path
        path = Path(raw)  # convert the typed text into a Path object so we can check it

        if not path.exists():
            # The file wasn't found at that location — ask again
            print(f'  File not found: {path}')
        elif path.suffix not in ('.xlsx', '.xls'):
            # The file exists but isn't an Excel file — ask again
            print(f'  Unsupported format "{path.suffix}" — please provide a .xlsx file.')
        else:
            # File exists and is the right format — return it
            return path


def prompt_column_choice(columns, prompt):
    """Display a numbered list and return the column the user picks."""

    # Print the question and show all column names as a numbered list
    print(f'\n{prompt}')
    for i, col in enumerate(columns):
        print(f'  [{i}] {col}')

    # Keep asking until the user types a valid number from the list
    while True:
        raw = input('Enter number: ').strip()  # read the user's input and remove leading/trailing spaces
        if raw.isdigit() and int(raw) < len(columns):
            # The user typed a valid number — return the corresponding column name
            return columns[int(raw)]
        print(f'  Please enter a number between 0 and {len(columns) - 1}.')


def prompt_path_columns(columns):
    """Display a numbered list and return the columns the user selects."""

    # Show all column names as a numbered list and allow multiple selections
    print('\nWhich columns contain the original file paths to check?')
    for i, col in enumerate(columns):
        print(f'  [{i}] {col}')
    print('Enter column numbers separated by spaces (e.g. 1 3):')

    # Keep asking until the user provides at least one valid selection
    while True:
        raw = input('> ').strip()  # read the user's input
        indices = raw.split()  # split the input into individual numbers (e.g. "1 3" → ["1", "3"])

        # Check that every entry is a valid number within the list range
        if all(idx.isdigit() and int(idx) < len(columns) for idx in indices) and indices:
            # Return the list of selected column names
            return [columns[int(idx)] for idx in indices]
        print(f'  Please enter valid numbers between 0 and {len(columns) - 1}.')


# ---------------------------------------------------------------------------
# Core check logic
# ---------------------------------------------------------------------------

def extract_patient_name(filepath, subject_id):
    """Return the patient name found in filepath, or None if not extractable."""

    # Split the file path into its individual folder/file components
    # e.g. '/data/P1001/Marcus_Aurelius-2024.03.15/file.nii'
    #   →  ('/', 'data', 'P1001', 'Marcus_Aurelius-2024.03.15', 'file.nii')
    parts = Path(str(filepath)).parts

    # Walk through each component of the path looking for the subject ID folder
    for i, part in enumerate(parts):

        # When we find the subject ID folder, the next folder should contain the patient name
        if part == subject_id and i + 1 < len(parts) - 1:

            # Try to match the Name-YYYY.MM.DD pattern on the next folder
            match = NAME_DATE_RE.match(parts[i + 1])

            if match:
                name = match.group(1)  # extract just the name portion (everything before the date)

                # Only return the name if it's different from the subject ID
                # (if they're the same, the path was already anonymised)
                if name != subject_id:
                    return name

    # No patient name could be extracted from this path
    return None


def run_check(df, id_col, path_columns):
    """Check that patient names from original paths are absent in _anonymized columns.

    Adds a <col>_check_status column for each checked column with 'pass' or 'fail'
    per row, then returns the updated DataFrame.
    """

    # Keep a running list of every failure found across all columns
    failures = []

    # Loop over each original path column the user selected
    for orig_col in path_columns:

        # Build the expected names for the anonymized and status columns
        anon_col   = f'{orig_col}_anonymized'   # e.g. 'nifti_path_anonymized'
        status_col = f'{orig_col}_check_status' # e.g. 'nifti_path_check_status'

        # If the anonymized column doesn't exist, anonymize.py hasn't been run for this column yet
        if anon_col not in df.columns:
            print(f'\n  WARNING: No "{anon_col}" column found — skipping {orig_col}.')
            continue  # skip to the next column

        print(f'\nChecking: {orig_col} -> {anon_col}')
        col_failures = 0  # count failures for this column

        statuses = []  # will hold 'pass' or 'fail' for every row in this column

        # Go through the spreadsheet one row at a time
        for idx, row in df.iterrows():
            original   = str(row[orig_col])   # the original file path before anonymization
            anonymized = str(row[anon_col])    # the anonymized file path after anonymization
            subject_id = str(row[id_col])      # the subject ID for this row (e.g. 'P1001')

            # Try to extract the patient name from the original path
            name = extract_patient_name(original, subject_id)

            if name is not None and name in anonymized:
                # The patient name was found — anonymization failed for this row
                print(f'  FAIL row {idx}: name "{name}" still present')
                print(f'       original  : {original}')
                print(f'       anonymized: {anonymized}')
                failures.append((idx, orig_col, name, anonymized))  # record the failure
                col_failures += 1
                statuses.append('fail')  # mark this row as failed
            else:
                # The patient name was not found in the anonymized path — all good
                statuses.append('pass')  # mark this row as passed

        # Write the pass/fail results as a new column in the spreadsheet
        df[status_col] = statuses

        # If no failures were found in this column, print a summary pass message
        if col_failures == 0:
            print('  PASS — no patient names found in anonymized paths')

    # Print an overall summary line
    print('\n' + '=' * 60)
    if failures:
        print(f'FAILED: {len(failures)} path(s) still contain patient names.')
    else:
        print('PASSED: All checked anonymized paths are free of patient names.')

    # Return the updated spreadsheet with the new status columns added
    return df


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    # Step 1: ask the user for the anonymized metadata Excel file
    input_path = prompt_input_file()
    df = pd.read_excel(input_path)  # load the spreadsheet into a table we can work with

    columns = list(df.columns)  # get the list of column names from the spreadsheet

    # Step 2: ask which column holds the subject IDs
    id_col = prompt_column_choice(columns, 'Which column contains the subject ID?')

    # Step 3: ask which columns contain the original file paths to check
    path_columns = prompt_path_columns(columns)

    # Step 4: run the check, then save the results back to the same Excel file
    df_out = run_check(df, id_col, path_columns)
    df_out.to_excel(input_path, index=False, na_rep='NA')  # overwrite the file with the updated table
    print(f'\nResults saved to: {input_path}')


# Only run main() if this script is being run directly (not imported by another script)
if __name__ == '__main__':
    main()
