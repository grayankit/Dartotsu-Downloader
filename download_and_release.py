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
import urllib.parse

# Constants
SCOPES = ['https://www.googleapis.com/auth/drive.readonly']
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
WAIT_TIME = 5  # Time in seconds to wait between uploads
GITHUB_DOWNLOADS_PATH = os.path.join(os.getcwd(), "downloads")

# Get service account JSON from command-line argument
if len(sys.argv) < 2:
    print("Usage: python download_and_release.py '<SERVICE_ACCOUNT_JSON>' [BUILD_TARGET] [COMMIT_SHA] [RELEASE_NOTES]")
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
BUILD_TARGET = os.getenv("BUILD_TARGET", "build.all")
COMMIT_SHA = os.getenv("COMMIT_SHA", "")
RELEASE_NOTES = os.getenv("RELEASE_NOTES", "")

# Folder IDs
FOLDER_IDS = [
    '1nWYex54zd58SVitJUCva91_4k1PPTdP3',  # Main folder
    '1S4QzdKz7ZofhiF5GAvjMdBvYK7YhndKM'   # APKs folder
]

# Build target to file patterns mapping
TARGET_PATTERNS = {
    'build': ['Dartotsu_windows.exe', 'Dartotsu_apks/*'],
    'build.all': ['*'],
    'build.apk': ['Dartotsu_apks/*'],
    'build.windows': ['Dartotsu_windows.exe'],
    'build.linux': ['Dartotsu_linux.zip'],
    'build.ios': ['Dartotsu-iOS-main.ipa'],
    'build.macos': ['Dartotsu-macos-main.dmg']
}

def fetch_files(folder_id, include_folders=False):
    query = f"'{folder_id}' in parents"
    if include_folders:
        query += " and (mimeType = 'application/vnd.google-apps.folder' or mimeType != 'application/vnd.google-apps.folder')"
    else:
        query += " and mimeType != 'application/vnd.google-apps.folder'"
    
    results = drive_service.files().list(
        q=query,
        fields="files(id, name, mimeType)"
    ).execute()
    return results.get('files', [])

def calculate_file_hash(file_path):
    hash_md5 = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()

def download_file(file_id, file_name):
    try:
        request = drive_service.files().get_media(fileId=file_id)
        file_path = os.path.join(GITHUB_DOWNLOADS_PATH, file_name)
        os.makedirs(GITHUB_DOWNLOADS_PATH, exist_ok=True)

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

def create_github_release(repo, token, tag, files, release_notes=""):
    release_url = f"https://api.github.com/repos/{repo}/releases"
    headers = {"Authorization": f"token {token}"}

    # Format release notes
    if release_notes:
        # URL decode the release notes
        release_notes = urllib.parse.unquote(release_notes)
        body = f"## Changes\n\n{release_notes}\n\n---\n\nAutomated release for {BUILD_TARGET}"
    else:
        body = f"Automated release for {BUILD_TARGET}"

    release_data = {"tag_name": tag, "name": tag, "body": body}
    release_response = requests.post(release_url, json=release_data, headers=headers)
    if release_response.status_code != 201:
        raise Exception(f"Failed to create release: {release_response.content}")

    release = release_response.json()
    upload_url = release["upload_url"].split("{")[0]

    for file_path in files:
        if file_path:
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

def configure_git_identity():
    subprocess.run(['git', 'config', '--global', 'user.name', 'Sheby'], check=True)
    subprocess.run(['git', 'config', '--global', 'user.email', 'sheby@gmail.com'], check=True)
    print("Configured Git identity.")

def commit_and_push():
    try:
        subprocess.run(['git', 'add', '.'], check=True)
        result = subprocess.run(['git', 'diff', '--cached', '--quiet'])
        if result.returncode == 0:
            print("No changes to commit.")
            return
        subprocess.run(['git', 'commit', '-m', f'Add downloaded files for {BUILD_TARGET}'], check=True)
        subprocess.run(['git', 'push', 'origin', 'main'], check=True)
        print("Committed and pushed files to GitHub.")
    except subprocess.CalledProcessError as e:
        print(f"Error during git operations: {e}")

def should_download_file(file_name, patterns):
    for pattern in patterns:
        if pattern == '*':
            return True
        elif pattern.endswith('/*'):
            folder_name = pattern[:-2]
            if file_name.startswith(folder_name):
                return True
        elif pattern == file_name:
            return True
    return False

def main():
    downloaded_files = []
    existing_files_hashes = {}
    
    # Determine patterns based on BUILD_TARGET or job statuses
    if BUILD_TARGET == "build.all":
        # Check individual job statuses to only download successful builds
        patterns = []
        if os.getenv("BUILD_ANDROID") == "success":
            patterns.append("Dartotsu_apks/*")
        if os.getenv("BUILD_WINDOWS") == "success":
            patterns.append("Dartotsu_windows.exe")
        if os.getenv("BUILD_LINUX") == "success":
            patterns.append("Dartotsu_linux.zip")
        if os.getenv("BUILD_IOS") == "success":
            patterns.append("Dartotsu-iOS-main.ipa")
        if os.getenv("BUILD_MACOS") == "success":
            patterns.append("Dartotsu-macos-main.dmg")
        
        if not patterns:
            print("No successful builds found. Nothing to download.")
            return
    else:
        patterns = TARGET_PATTERNS.get(BUILD_TARGET, ['*'])
    
    print(f"Processing build target: {BUILD_TARGET}")
    print(f"File patterns: {patterns}")

    # Download files from all folders
    for folder_id in FOLDER_IDS:
        print(f"Fetching files from folder ID: {folder_id}")
        items = fetch_files(folder_id, include_folders=True)
        
        for item in items:
            if item['mimeType'] == 'application/vnd.google-apps.folder':
                # Process subfolder
                subfolder_files = fetch_files(item['id'], include_folders=False)
                for file in subfolder_files:
                    file_name = f"{item['name']}/{file['name']}"
                    if should_download_file(file_name, patterns):
                        print(f"Found file in subfolder: {file_name}")
                        file_path = download_file(file['id'], file_name)
                        if file_path:
                            file_hash = calculate_file_hash(file_path)
                            if file_name not in existing_files_hashes or existing_files_hashes[file_name] != file_hash:
                                downloaded_files.append(file_path)
                                existing_files_hashes[file_name] = file_hash
                            else:
                                print(f"File {file_name} is unchanged. Skipping.")
            else:
                # Process top-level file
                if should_download_file(item['name'], patterns):
                    print(f"Found top-level file: {item['name']}")
                    file_path = download_file(item['id'], item['name'])
                    if file_path:
                        file_hash = calculate_file_hash(file_path)
                        if item['name'] not in existing_files_hashes or existing_files_hashes[item['name']] != file_hash:
                            downloaded_files.append(file_path)
                            existing_files_hashes[item['name']] = file_hash
                        else:
                            print(f"File {item['name']} is unchanged. Skipping.")

    # If new/changed files were downloaded
    if downloaded_files:
        configure_git_identity()
        commit_and_push()

        # Use commit SHA from triggering workflow if available
        tag_name = COMMIT_SHA[:7] if COMMIT_SHA else "latest"
        print(f"Using tag: {tag_name}")

        # Check for existing release
        release_check_url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/tags/{tag_name}"
        headers = {"Authorization": f"token {GITHUB_TOKEN}"}
        check_response = requests.get(release_check_url, headers=headers)

        if check_response.status_code == 200:
            print(f"Release with tag '{tag_name}' already exists. Skipping release creation.")
        else:
            create_github_release(GITHUB_REPO, GITHUB_TOKEN, tag_name, downloaded_files, RELEASE_NOTES)

        # Upload to Telegram (commented out as in original)
        # for file_path in downloaded_files:
        #     file_name = os.path.basename(file_path)
        #     upload_to_telegram(file_path, file_name)
        #     time.sleep(WAIT_TIME)
    else:
        print("No new or changed files to commit, release, or upload.")

if __name__ == "__main__":
    main()
