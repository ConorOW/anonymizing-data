"""
Anonymization Check
===================
Interactively loads the anonymized_metadata.xlsx produced by anonymize.py
and verifies that no patient names remain in the anonymized path columns.

For each original path it extracts the patient name using the same
Name-YYYY.MM.DD regex used during anonymization, then checks that name
is absent from the corresponding _anonymized column.
"""

import re
import glob
import readline
from pathlib import Path

import pandas as pd


NAME_DATE_RE = re.compile(r'^(.+?)(-\d{4}\.\d{2}\.\d{2}.*)$')


# ---------------------------------------------------------------------------
# Tab completion (same as anonymize.py)
# ---------------------------------------------------------------------------

def _setup_tab_completion():
    def path_completer(text, state):
        matches = glob.glob(text + '*')
        matches = [m + '/' if Path(m).is_dir() else m for m in matches]
        return matches[state] if state < len(matches) else None

    readline.set_completer(path_completer)
    readline.parse_and_bind('tab: complete')


_setup_tab_completion()


# ---------------------------------------------------------------------------
# Interactive input helpers
# ---------------------------------------------------------------------------

def prompt_input_file():
    """Prompt for the anonymized metadata xlsx until a valid file is given."""
    while True:
        raw = input('Enter path to anonymized metadata file (XLSX): ').strip()
        path = Path(raw)
        if not path.exists():
            print(f'  File not found: {path}')
        elif path.suffix not in ('.xlsx', '.xls'):
            print(f'  Unsupported format "{path.suffix}" — please provide a .xlsx file.')
        else:
            return path


def prompt_column_choice(columns, prompt):
    """Display a numbered list and return the column the user picks."""
    print(f'\n{prompt}')
    for i, col in enumerate(columns):
        print(f'  [{i}] {col}')
    while True:
        raw = input('Enter number: ').strip()
        if raw.isdigit() and int(raw) < len(columns):
            return columns[int(raw)]
        print(f'  Please enter a number between 0 and {len(columns) - 1}.')


def prompt_path_columns(columns):
    """Display a numbered list and return the columns the user selects."""
    print('\nWhich columns contain the original file paths to check?')
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
# Core check logic
# ---------------------------------------------------------------------------

def extract_patient_name(filepath, subject_id):
    """Return the patient name found in filepath, or None if not extractable."""
    parts = Path(str(filepath)).parts
    for i, part in enumerate(parts):
        if part == subject_id and i + 1 < len(parts) - 1:
            match = NAME_DATE_RE.match(parts[i + 1])
            if match:
                name = match.group(1)
                if name != subject_id:
                    return name
    return None


def run_check(df, id_col, path_columns):
    """Check that patient names from original paths are absent in _anonymized columns.

    Adds a <col>_check_status column for each checked column with 'pass' or 'fail'
    per row, then returns the updated DataFrame.
    """
    failures = []

    for orig_col in path_columns:
        anon_col   = f'{orig_col}_anonymized'
        status_col = f'{orig_col}_check_status'

        if anon_col not in df.columns:
            print(f'\n  WARNING: No "{anon_col}" column found — skipping {orig_col}.')
            continue

        print(f'\nChecking: {orig_col} -> {anon_col}')
        col_failures = 0

        statuses = []

        for idx, row in df.iterrows():
            original   = str(row[orig_col])
            anonymized = str(row[anon_col])
            subject_id = str(row[id_col])

            name = extract_patient_name(original, subject_id)

            if name is not None and name in anonymized:
                print(f'  FAIL row {idx}: name "{name}" still present')
                print(f'       original  : {original}')
                print(f'       anonymized: {anonymized}')
                failures.append((idx, orig_col, name, anonymized))
                col_failures += 1
                statuses.append('fail')
            else:
                statuses.append('pass')

        df[status_col] = statuses

        if col_failures == 0:
            print('  PASS — no patient names found in anonymized paths')

    print('\n' + '=' * 60)
    if failures:
        print(f'FAILED: {len(failures)} path(s) still contain patient names.')
    else:
        print('PASSED: All checked anonymized paths are free of patient names.')

    return df


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    # Step 1: load the file
    input_path = prompt_input_file()
    df = pd.read_excel(input_path)

    columns = list(df.columns)

    # Step 2: pick the subject ID column
    id_col = prompt_column_choice(columns, 'Which column contains the subject ID?')

    # Step 3: pick the original path columns to check
    path_columns = prompt_path_columns(columns)

    # Step 4: run the check and write results back to the same file
    df_out = run_check(df, id_col, path_columns)
    df_out.to_excel(input_path, index=False, na_rep='NA')
    print(f'\nResults saved to: {input_path}')


if __name__ == '__main__':
    main()
