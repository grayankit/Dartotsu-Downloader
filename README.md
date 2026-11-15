# [Dartotsu](https://github.com/aayush2622/Dartotsu) Download and Release Automation

This repository automates the process of downloading files from Google Drive folders linked to Dartotsu, creating a versioned release, and uploading the downloaded files to GitHub. The files are fetched from specified Google Drive folders, and a new release is automatically created with an incremented version tag.

## Features
- Downloads files from specified Dartotsu Google Drive folders.
- Automatically creates versioned releases on GitHub (e.g., `v1.0.0`, `v1.0.1`).
- If a release with the same tag already exists, the previous release is deleted and the new one is uploaded.
- Supports fetching from multiple Google Drive folders.

## Prerequisites

1. **Google Drive API credentials**: You need a service account JSON file to authenticate with Google Drive.
2. **GitHub Personal Access Token**: You will need a GitHub token to authenticate and push the release to your GitHub repository.
3. **Python 3.x**: Ensure Python is installed and available in your environment.

### Required Python Libraries:
- `google-api-python-client`
- `google-auth`
- `google-auth-oauthlib`
- `google-auth-httplib2`
- `requests`

Install the required libraries using `pip`:

```bash
pip install google-api-python-client google-auth google-auth-oauthlib google-auth-httplib2 requests
```

## Setup

1. **Clone this repository**:
   ```bash
   git clone https://github.com/Shebyyy/Dartotsu-Download.git
   cd Dartotsu-Download
   ```

2. **Configure Google Drive credentials**:
   - Create a service account in the Google Cloud Console and download the JSON key file.
   - Rename the downloaded file to `service_account.json` and place it in the root of this repository.

3. **Set up your GitHub Token**:
   - Generate a Personal Access Token (PAT) from GitHub.
   - Add your `GITHUB_TOKEN` in the environment variables or GitHub Secrets if using GitHub Actions.

4. **Add Folder IDs**:
   - Add the Google Drive folder IDs from which you want to download files. You can add more folders as needed.
   - The `FOLDER_IDS` list in the script already contains example folder IDs.

5. **Run the Script**:
   - You can run the script manually or set up GitHub Actions for automation.

   To run the script locally, execute:
   ```bash
   python download_and_release.py
   ```

## How It Works

1. **Fetch Files from Dartotsu Folders**: The script fetches all files from the specified Google Drive folders associated with Dartotsu.
2. **Download Files**: Each file is downloaded and saved in a local folder.
3. **Create Versioned GitHub Release**:
   - The script checks the latest release tag in the GitHub repository and increments the version number.
   - If a release with the same tag exists, it deletes the old release and uploads the new one with the updated tag.
4. **Upload Files to GitHub**: The script uploads all downloaded files as assets in the newly created GitHub release.

## Example Usage

You can manually trigger the release creation by running the script, or configure it to run automatically via GitHub Actions.

### GitHub Action Workflow:

```yaml
name: Generate Download Links and Deploy

on:
  push:
    branches:
      - main
  workflow_dispatch:

jobs:
  generate-and-deploy:
    runs-on: ubuntu-latest

    steps:
      - name: Checkout repository
        uses: actions/checkout@v3

      - name: Set up Python
        uses: actions/setup-python@v6
        with:
          python-version: "3.12"

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install google-api-python-client google-auth google-auth-oauthlib google-auth-httplib2 requests

      - name: Run download and release script
        env:
          GITHUB_REPOSITORY: ${{ secrets.GITHUB_REPOSITORY }}
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: |
          python download_and_release.py
```

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
