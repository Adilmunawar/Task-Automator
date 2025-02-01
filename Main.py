import os
import shutil
import time
import logging
from tqdm import tqdm
from datetime import datetime, timedelta
import winsound
import json
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.http import MediaFileUpload
import dropbox
import hashlib
from concurrent.futures import ThreadPoolExecutor
import schedule
import tkinter as tk
from tkinter import filedialog
from PIL import Image
from PIL.ExifTags import TAGS

# Setting up the log files
logging.basicConfig(filename='file_organizer.log', level=logging.INFO, 
                    format='%(asctime)s - %(message)s')

# Email configuration
email_sender = 'youremail@example.com'
email_receiver = 'receiveremail@example.com'
email_subject = "File Organization Task Completed"
email_body_template = """
The file organization task has been completed successfully.

Summary:
- Total files processed: {total_files}
- Files moved: {moved_files}
- Files skipped (size/date): {skipped_files}
- Errors: {errors}

For more details, please check the attached log file.

Thank you for using the file organizer.
"""

# Google Drive API credentials file (OAuth2.0)
CLIENT_SECRET_FILE = 'client_secret.json'
API_NAME = 'drive'
API_VERSION = 'v3'
SCOPES = ['https://www.googleapis.com/auth/drive.file']

# Dropbox API credentials
DROPBOX_ACCESS_TOKEN = 'your_dropbox_access_token'

# File category mapping (can be customized)
extensions_map = {
    'Images': ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff'],
    'Videos': ['.mp4', '.mkv', '.avi', '.mov'],
    'Documents': ['.pdf', '.docx', '.txt', '.xlsx'],
    'Audios': ['.mp3', '.wav', '.flac', '.aac'],
    'Archives': ['.zip', '.tar', '.rar', '.7z']
}

# Function to move files
def move_file(file, destination_folder):
    try:
        if not os.path.exists(destination_folder):
            os.makedirs(destination_folder)
        shutil.move(file, destination_folder)
        logging.info(f"Moved: {file} -> {destination_folder}")
    except Exception as e:
        logging.error(f"Error moving {file}: {e}")

# Backup function
def backup_file(file_path):
    backup_folder = os.path.join(os.path.dirname(file_path), "backup")
    if not os.path.exists(backup_folder):
        os.makedirs(backup_folder)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_path = os.path.join(backup_folder, f"{timestamp}_{os.path.basename(file_path)}")
    shutil.copy(file_path, backup_path)
    logging.info(f"Backed up: {file_path} -> {backup_path}")

# Cloud backup to Google Drive
def cloud_backup_google_drive(file_path):
    try:
        # Authenticate with Google Drive
        flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET_FILE, SCOPES)
        creds = flow.run_local_server(port=0)
        service = build(API_NAME, API_VERSION, credentials=creds)
        
        # Upload files to Google Drive
        file_metadata = {'name': os.path.basename(file_path)}
        media = MediaFileUpload(file_path, resumable=True)
        file = service.files().create(body=file_metadata, media_body=media, fields='id').execute()
        logging.info(f"Cloud Backup Successful: {file_path} uploaded to Google Drive.")
    except Exception as e:
        logging.error(f"Cloud Backup Failed for {file_path}: {e}")

# Cloud backup to Dropbox
def cloud_backup_dropbox(file_path):
    try:
        # Authenticate with Dropbox
        dbx = dropbox.Dropbox(DROPBOX_ACCESS_TOKEN)
        
        # Upload file to Dropbox
        with open(file_path, 'rb') as f:
            dbx.files_upload(f.read(), f'/backup/{os.path.basename(file_path)}', mode=dropbox.files.WriteMode.overwrite)
        logging.info(f"Cloud Backup Successful: {file_path} uploaded to Dropbox.")
    except Exception as e:
        logging.error(f"Cloud Backup Failed for {file_path}: {e}")

# Function to calculate hash for file integrity check
def calculate_hash(file_path):
    hash_md5 = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()

# Function to verify file integrity after move
def verify_integrity(original_file, destination_file):
    original_hash = calculate_hash(original_file)
    destination_hash = calculate_hash(destination_file)
    return original_hash == destination_hash

# Function to rename files if same name exists
def rename_if_exists(file_path, destination_folder):
    filename = os.path.basename(file_path)
    destination_path = os.path.join(destination_folder, filename)
    
    # If file exists, rename it
    if os.path.exists(destination_path):
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename, ext = os.path.splitext(filename)
        filename = f"{filename}_{timestamp}{ext}"
        destination_path = os.path.join(destination_folder, filename)
    
    return destination_path

# Function to filter files based on size and modification date
def filter_file(file_path, min_size_mb=1, days_old=7):
    file_size = os.path.getsize(file_path) / (1024 * 1024)  # Size in MB
    file_mod_time = datetime.fromtimestamp(os.path.getmtime(file_path))
    cutoff_date = datetime.now() - timedelta(days=days_old)
    
    if file_size < min_size_mb or file_mod_time < cutoff_date:
        return False
    return True

# Function to send email notification
def send_email_notification(summary):
    try:
        email_body = email_body_template.format(**summary)
        
        msg = MIMEMultipart()
        msg['From'] = email_sender
        msg['To'] = email_receiver
        msg['Subject'] = email_subject
        msg.attach(MIMEText(email_body, 'plain'))
        
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(email_sender, 'yourpassword')  # Use environment variables for security
        text = msg.as_string()
        server.sendmail(email_sender, email_receiver, text)
        server.quit()
        
        logging.info("Email notification sent successfully.")
    except Exception as e:
        logging.error(f"Failed to send email notification: {e}")

# Function to organize files
def organize_files(path_to_organize):
    total_files = 0
    moved_files = 0
    skipped_files = 0
    errors = 0

    files = [f for f in os.listdir(path_to_organize) if os.path.isfile(os.path.join(path_to_organize, f))]
    
    for file in tqdm(files, desc="Organizing Files", unit="file"):
        total_files += 1
        file_path = os.path.join(path_to_organize, file)
        file_ext = os.path.splitext(file)[1].lower()

        # Skip files that don't meet filtering criteria (size, modification date)
        if not filter_file(file_path):
            skipped_files += 1
            logging.info(f"Skipping file (doesn't meet criteria): {file_path}")
            continue
        
        try:
            # Backup file before moving and cloud backup
            backup_file(file_path)
            cloud_backup_google_drive(file_path)
            cloud_backup_dropbox(file_path)

            # Check which category the file belongs to
            moved = False
            for category, exts in extensions_map.items():
                if file_ext in exts:
                    destination_folder = os.path.join(path_to_organize, category)
                    destination_path = rename_if_exists(file_path, destination_folder)
                    move_file(file_path, destination_path)
                    moved_files += 1
                    moved = True
                    break
            
            if not moved:
                logging.warning(f"File type not recognized: {file_path}")
                errors += 1

        except Exception as e:
            errors += 1
            logging.error(f"Error processing {file_path}: {e}")
    
    # Notify completion
    logging.info("File Organization Complete.")
    winsound.Beep(1000, 500)  # Notify user with a beep sound

    # Send email with summary
    summary = {
        'total_files': total_files,
        'moved_files': moved_files,
        'skipped_files': skipped_files,
        'errors': errors
    }
    send_email_notification(summary)

# Function to load user configuration from a file
def load_user_config():
    with open('config.json', 'r') as f:
        return json.load(f)

# Function to create GUI using Tkinter
def create_gui():
    root = tk.Tk()
    root.title("File Organizer")

    def browse_folder():
        folder = filedialog.askdirectory()
        path_label.config(text=folder)

    path_label = tk.Label(root, text="No folder selected")
    path_label.pack(pady=20)

    browse_button = tk.Button(root, text="Browse", command=browse_folder)
    browse_button.pack(pady=10)

    start_button = tk.Button(root, text="Start Organizing", command=lambda: organize_files(path_label.cget("text")))
    start_button.pack(pady=20)

    root.mainloop()

# Main function to run the task
if __name__ == '__main__':
    create_gui()
