import os
import io
import time
import hashlib
import requests
import json
import sys
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from google.oauth2 import service_account
from googleapiclient.errors import HttpError
import re
import subprocess

# Constants
SCOPES = ['https://www.googleapis.com/auth/drive.readonly']
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
WAIT_TIME = 5  # Time in seconds to wait between uploads to avoid rate limits
GITHUB_DOWNLOADS_PATH = os.path.join(os.getcwd(), "downloads")

# ✅ Get service account JSON from command-line argument
if len(sys.argv) < 2:
    print("Usage: python download_and_release.py '<SERVICE_ACCOUNT_JSON>'")
    sys.exit(1)

try:
    service_account_info = json.loads(sys.argv[1])
    credentials = service_account.Credentials.from_service_account_info(service_account_info, scopes=SCOPES)
    drive_service = build('drive', 'v3', credentials=credentials)
except Exception as e:
    print("Invalid service account JSON:", str(e))
    sys.exit(1)

# GitHub environment
GITHUB_REPO = os.getenv("GITHUB_REPOSITORY")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")

FOLDER_IDS = [
    '1nWYex54zd58SVitJUCva91_4k1PPTdP3',
    '1S4QzdKz7ZofhiF5GAvjMdBvYK7YhndKM'
]

# Function to fetch files in a folder
def fetch_files(folder_id):
    results = drive_service.files().list(
        q=f"'{folder_id}' in parents",
        fields="files(id, name)"
    ).execute()
    return results.get('files', [])

# Function to calculate file hash (MD5)
def calculate_file_hash(file_path):
    hash_md5 = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()

# Function to download a file from Google Drive (overwrites existing files)
def download_file(file_id, file_name):
    try:
        request = drive_service.files().get_media(fileId=file_id)
        file_path = os.path.join(GITHUB_DOWNLOADS_PATH, file_name)
        
        # Create the directory structure if it doesn't exist
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        
        with io.FileIO(file_path, "wb") as fh:
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done:
                status, done = downloader.next_chunk()
                print(f"Downloading {file_name}... {int(status.progress() * 100)}%")
        return file_path
    except HttpError as e:
        if "fileNotDownloadable" in str(e):
            print(f"Skipping non-downloadable file: {file_name}")
            return None
        else:
            raise

# Function to create a GitHub release and upload files
def create_github_release(repo, token, tag, files):
    release_url = f"https://api.github.com/repos/{repo}/releases"
    headers = {"Authorization": f"token {token}"}

    # Create a new release
    release_data = {"tag_name": tag, "name": tag, "body": "Automated release with uploaded files"}
    release_response = requests.post(release_url, json=release_data, headers=headers)
    if release_response.status_code != 201:
        raise Exception(f"Failed to create release: {release_response.content}")

    release = release_response.json()
    upload_url = release["upload_url"].split("{")[0]

    # Upload files to the release
    for file_path in files:
        if file_path:  # Skip if file_path is None
            file_name = os.path.basename(file_path)
            with open(file_path, "rb") as f:
                headers.update({"Content-Type": "application/octet-stream"})
                upload_response = requests.post(
                    f"{upload_url}?name={file_name}", headers=headers, data=f
                )
                if upload_response.status_code not in (200, 201):
                    raise Exception(f"Failed to upload file {file_name}: {upload_response.content}")
            print(f"Uploaded {file_name} to GitHub release.")
    print(f"Release {tag} created successfully.")

# # Function to upload file to Telegram
# def upload_to_telegram(file_path, file_name):
#     url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendDocument"
#     file_size = os.path.getsize(file_path)

#     if file_size > 50 * 1024 * 1024:
#         print(f"File too large for Telegram: {file_name} ({file_size / (1024 * 1024):.2f} MB)")
#         return

#     with open(file_path, 'rb') as file:
#         response = requests.post(url, data={'chat_id': TELEGRAM_CHAT_ID}, files={'document': file})
#         if response.status_code == 200:
#             print(f"Successfully uploaded {file_name} to Telegram.")
#         else:
#             print(f"Failed to upload {file_name} to Telegram: {response.json()}")


def get_external_commit_hash(repo):
    url = f"https://api.github.com/repos/{repo}/commits"
    response = requests.get(url)

    if response.status_code == 200:
        commit_sha = response.json()[0].get('sha')
        return commit_sha[:7] if commit_sha else "0000000"
    else:
        print(f"Failed to fetch commits from {repo}: {response.text}")
        return "00000"
# Function to configure git user identity
def configure_git_identity():
    subprocess.run(['git', 'config', '--global', 'user.name', 'Sheby'], check=True)  # Replace with your name
    subprocess.run(['git', 'config', '--global', 'user.email', 'sheby@gmail.com'], check=True)  # Replace with your email
    print("Configured Git identity.")

# Function to commit and push changes to GitHub
def commit_and_push():
    try:
        subprocess.run(['git', 'add', '.'], check=True)
        result = subprocess.run(['git', 'diff', '--cached', '--quiet'])
        if result.returncode == 0:
            print("No changes to commit.")
            return
        subprocess.run(['git', 'commit', '-m', 'Add downloaded files'], check=True)
        subprocess.run(['git', 'push', 'origin', 'main'], check=True)
        print("Committed and pushed files to GitHub.")
    except subprocess.CalledProcessError as e:
        print(f"Error during git operations: {e}")

# Main script logic
def main():
    downloaded_files = []
    existing_files_hashes = {}

    # Step 1: Download files from all folders
    for folder_id in FOLDER_IDS:
        print(f"Fetching files from folder ID: {folder_id}")
        files = fetch_files(folder_id)
        if not files:
            print(f"No files found in folder ID: {folder_id}")
            continue

        for file in files:
            file_id = file['id']
            file_name = file['name']
            print(f"Found file: {file_name}")
            file_path = download_file(file_id, file_name)
            if file_path:
                file_hash = calculate_file_hash(file_path)
                if file_name not in existing_files_hashes or existing_files_hashes[file_name] != file_hash:
                    downloaded_files.append(file_path)
                    existing_files_hashes[file_name] = file_hash
                else:
                    print(f"File {file_name} is unchanged. Skipping release and upload.")

    # Step 2: If new/changed files were downloaded
    if downloaded_files:
        configure_git_identity()
        commit_and_push()

        # Generate tag from external repo commit hash
        EXTERNAL_REPO = "aayush2622/Dartotsu"
        tag_name = get_external_commit_hash(EXTERNAL_REPO)
        print(f"Using tag based on external commit hash: {tag_name}")

        # ✅ Avoid duplicate release
        release_check_url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/tags/{tag_name}"
        headers = {"Authorization": f"token ${GITHUB_TOKEN}"}
        check_response = requests.get(release_check_url, headers=headers)

        if check_response.status_code == 200:
            print(f"Release with tag '{tag_name}' already exists. Skipping release creation.")
        else:
            create_github_release(GITHUB_REPO, GITHUB_TOKEN, tag_name, downloaded_files)

        # Upload to Telegram
        for file_path in downloaded_files:
            file_name = os.path.basename(file_path)
            # upload_to_telegram(file_path, file_name)
            time.sleep(WAIT_TIME)
    else:
        print("No new or changed files to commit, release, or upload.")

if __name__ == "__main__":
    main()
