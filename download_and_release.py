import os
import io
import time
import hashlib
import requests
import json
import sys
import fnmatch
import shutil
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from google.oauth2 import service_account
from googleapiclient.errors import HttpError
import subprocess

# Constants
SCOPES = ['https://www.googleapis.com/auth/drive.readonly']
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
WAIT_TIME = 5  # Time in seconds to wait between uploads to avoid rate limits
GITHUB_DOWNLOADS_PATH = os.path.join(os.getcwd(), "downloads")
GITHUB_BRANCH = os.getenv("GITHUB_BRANCH", "main")  # Make branch name configurable

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
COMMIT_SHA = os.getenv("COMMIT_SHA", "")  # Get commit SHA from environment
RELEASE_NOTES = os.getenv("RELEASE_NOTES", "")  # Get release notes from environment
BUILD_TARGET = os.getenv("BUILD_TARGET", "build.all")  # Get build target from environment

FOLDER_IDS = [
    '1nWYex54zd58SVitJUCva91_4k1PPTdP3',
    '1S4QzdKz7ZofhiF5GAvjMdBvYK7YhndKM'
]

# Build target to file patterns mapping
TARGET_PATTERNS = {
    'build': ['Dartotsu_windows.exe', '*.apk'],
    'build.all': ['*'],
    'build.apk': ['*.apk'],
    'build.windows': ['Dartotsu_windows.exe'],
    'build.linux': ['Dartotsu_linux.zip'],
    'build.ios': ['Dartotsu-iOS-main.ipa'],
    'build.macos': ['Dartotsu-macos-main.dmg'],
    'build.none': []  # No files to download
}

# Function to check if a file should be downloaded based on build target
def should_download_file(file_name, patterns):
    for pattern in patterns:
        if fnmatch.fnmatch(file_name, pattern):
            return True
    return False

# Function to fetch files in a folder
def fetch_files(folder_id):
    results = drive_service.files().list(
        q=f"'{folder_id}' in parents",
        fields="files(id, name, mimeType)"
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
def download_file(file_id, file_name, mime_type):
    # Skip folders
    if mime_type == 'application/vnd.google-apps.folder':
        print(f"Skipping folder: {file_name}")
        return None
        
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
def create_github_release(repo, token, tag, files, release_notes=""):
    release_url = f"https://api.github.com/repos/{repo}/releases"
    headers = {"Authorization": f"token {token}"}

    # First check if release already exists
    check_url = f"https://api.github.com/repos/{repo}/releases/tags/{tag}"
    check_response = requests.get(check_url, headers=headers)
    
    # Format release notes
    if release_notes:
        try:
            from urllib.parse import unquote
            release_notes = unquote(release_notes)
        except:
            pass
        body = f"## Changes\n\n{release_notes}\n\n---\n\nAutomated release for {BUILD_TARGET}"
    else:
        body = f"Automated release for {BUILD_TARGET}"
    
    if check_response.status_code == 200:
        print(f"Release with tag '{tag}' already exists. Updating existing release.")
        release = check_response.json()
        release_id = release['id']
        
        # Delete existing assets
        assets_url = f"https://api.github.com/repos/{repo}/releases/{release_id}/assets"
        assets_response = requests.get(assets_url, headers=headers)
        if assets_response.status_code == 200:
            assets = assets_response.json()
            for asset in assets:
                asset_id = asset['id']
                delete_url = f"https://api.github.com/repos/{repo}/releases/assets/{asset_id}"
                delete_response = requests.delete(delete_url, headers=headers)
                if delete_response.status_code != 204:
                    print(f"Warning: Failed to delete asset {asset['name']}: {delete_response.status_code}")
        
        # Update the release
        update_url = f"https://api.github.com/repos/{repo}/releases/{release_id}"
        update_data = {"tag_name": tag, "name": tag, "body": body}
        update_response = requests.patch(update_url, json=update_data, headers=headers)
        if update_response.status_code != 200:
            raise Exception(f"Failed to update release: {update_response.content}")
        
        release = update_response.json()
    else:
        # Create a new release
        release_data = {"tag_name": tag, "name": tag, "body": body}
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
    print(f"Release {tag} created/updated successfully.")

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
    subprocess.run(['git', 'config', '--global', 'user.name', 'Sheby'], check=True)
    subprocess.run(['git', 'config', '--global', 'user.email', 'sheby@gmail.com'], check=True)
    print("Configured Git identity.")

# Function to commit and push only the specified files
def commit_and_push(files_to_commit):
    try:
        # Add only the files we want to commit
        for file_path in files_to_commit:
            if file_path:  # Skip if file_path is None
                subprocess.run(['git', 'add', file_path], check=True)
        
        # Check if there are any changes to commit
        result = subprocess.run(['git', 'diff', '--cached', '--quiet'])
        if result.returncode == 0:
            print("No changes to commit.")
            return
        
        subprocess.run(['git', 'commit', '-m', f'Add downloaded files for {BUILD_TARGET}'], check=True)
        
        # Check if the branch exists on remote
        try:
            # First try to push with upstream set
            subprocess.run(['git', 'push', '-u', 'origin', GITHUB_BRANCH], check=True)
            print(f"Pushed to {GITHUB_BRANCH} branch with upstream set.")
        except subprocess.CalledProcessError:
            try:
                # If that fails, try a regular push
                subprocess.run(['git', 'push', 'origin', GITHUB_BRANCH], check=True)
                print(f"Pushed to {GITHUB_BRANCH} branch.")
            except subprocess.CalledProcessError as e:
                print(f"Error during git push: {e}")
                print(f"Trying to determine the correct branch name...")
                
                # Get the current branch name
                result = subprocess.run(['git', 'branch', '--show-current'], 
                                      capture_output=True, text=True)
                current_branch = result.stdout.strip()
                if current_branch:
                    print(f"Current branch is: {current_branch}")
                    try:
                        subprocess.run(['git', 'push', 'origin', current_branch], check=True)
                        print(f"Successfully pushed to {current_branch} branch.")
                    except subprocess.CalledProcessError as e2:
                        print(f"Failed to push to {current_branch}: {e2}")
                        raise
                else:
                    raise
                
    except subprocess.CalledProcessError as e:
        print(f"Error during git operations: {e}")
        # Continue with release creation even if git push fails

# Function to clean up old files not in the current release
def cleanup_old_files(current_files):
    try:
        # Get all files in the downloads directory
        existing_files = []
        for root, _, files in os.walk(GITHUB_DOWNLOADS_PATH):
            for file in files:
                existing_files.append(os.path.join(root, file))
        
        # Determine which files to keep (those in current_files)
        files_to_keep = set(current_files)
        
        # Delete files that aren't in the current release
        for file_path in existing_files:
            if file_path not in files_to_keep:
                print(f"Removing old file: {file_path}")
                os.remove(file_path)
                
        # Remove empty directories
        for root, dirs, _ in os.walk(GITHUB_DOWNLOADS_PATH, topdown=False):
            for dir in dirs:
                dir_path = os.path.join(root, dir)
                if not os.listdir(dir_path):
                    print(f"Removing empty directory: {dir_path}")
                    os.rmdir(dir_path)
                    
    except Exception as e:
        print(f"Error during cleanup: {e}")

# Main script logic
def main():
    downloaded_files = []
    existing_files_hashes = {}
    
    # Split BUILD_TARGET into individual targets
    targets = BUILD_TARGET.split()
    print(f"Processing build targets: {targets}")
    
    # Get patterns for all targets
    all_patterns = []
    for target in targets:
        patterns = TARGET_PATTERNS.get(target, [])
        all_patterns.extend(patterns)
        print(f"Patterns for {target}: {patterns}")
    
    # Remove duplicates
    all_patterns = list(set(all_patterns))
    print(f"Combined patterns: {all_patterns}")

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
            mime_type = file.get('mimeType', '')
            
            # Check if this file should be downloaded based on any of the patterns
            if should_download_file(file_name, all_patterns):
                print(f"Found file matching build target: {file_name}")
                file_path = download_file(file_id, file_name, mime_type)
                if file_path:
                    file_hash = calculate_file_hash(file_path)
                    if file_name not in existing_files_hashes or existing_files_hashes[file_name] != file_hash:
                        downloaded_files.append(file_path)
                        existing_files_hashes[file_name] = file_hash
                    else:
                        print(f"File {file_name} is unchanged. Skipping release and upload.")
            else:
                print(f"Skipping file {file_name} (does not match any build target)")

    # Step 2: If new/changed files were downloaded
    if downloaded_files:
        # Clean up old files not in the current release
        cleanup_old_files(downloaded_files)
        
        configure_git_identity()
        commit_and_push(downloaded_files)

        # Use the passed commit SHA if available, otherwise fall back to fetching it
        if COMMIT_SHA:
            tag_name = COMMIT_SHA[:7]
            print(f"Using passed commit SHA: {tag_name}")
        else:
            EXTERNAL_REPO = "aayush2622/Dartotsu"
            tag_name = get_external_commit_hash(EXTERNAL_REPO)
            print(f"Using tag based on external commit hash: {tag_name}")

        # Create or update release with release notes
        create_github_release(GITHUB_REPO, GITHUB_TOKEN, tag_name, downloaded_files, RELEASE_NOTES)

        # Upload to Telegram
        for file_path in downloaded_files:
            file_name = os.path.basename(file_path)
            # upload_to_telegram(file_path, file_name)
            time.sleep(WAIT_TIME)
    else:
        print("No new or changed files to commit, release, or upload.")

if __name__ == "__main__":
    main()
