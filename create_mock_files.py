"""
Create mock NIfTI files matching the absolute paths in metadata-example.csv.
Run this once to set up a test dataset before running anonymize.py.
"""

import pandas as pd
from pathlib import Path

HERE = Path(__file__).parent

CSV_PATH = HERE / 'metadata-example.csv'


def create_mock_files(csv_path):
    df = pd.read_csv(csv_path)

    print(f'Creating mock files from: {csv_path}')
    print('-' * 60)

    for _, row in df.iterrows():
        file_path = Path(row['nifti_path'])
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.touch()
        print(f'  Created: {file_path}')

    print('-' * 60)
    print(f'Done. {len(df)} files created.')


if __name__ == '__main__':
    create_mock_files(CSV_PATH)
