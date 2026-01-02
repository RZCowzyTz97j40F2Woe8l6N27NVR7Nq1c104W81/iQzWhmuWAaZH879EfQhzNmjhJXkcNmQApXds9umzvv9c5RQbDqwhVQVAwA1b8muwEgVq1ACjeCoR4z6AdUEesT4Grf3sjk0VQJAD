import os, subprocess, csv, zipfile, plistlib, shutil, time, logging, re
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed
from multiprocessing import cpu_count
import tempfile
import threading

# Set up logging
logging.basicConfig(filename="app_processing.log", level=logging.INFO, 
                   format='%(asctime)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')

# Create icons directory if it doesn't exist
icons_dir = "icons"
os.makedirs(icons_dir, exist_ok=True)

# Clean up any existing invalid icon files
def cleanup_invalid_icons():
    """Remove any invalid icon files (empty names, etc.)"""
    if os.path.exists(icons_dir):
        for file in os.listdir(icons_dir):
            if file.endswith('.png'):
                # Remove files with empty or invalid names
                if (file == '.png' or file == '..png' or 
                    file.startswith('.') or len(file) < 5):
                    try:
                        os.remove(os.path.join(icons_dir, file))
                        logging.info(f"Removed invalid icon file: {file}")
                    except Exception as e:
                        logging.warning(f"Could not remove invalid icon {file}: {e}")

# Clean up on startup
cleanup_invalid_icons()

# Thread-safe counter for progress tracking
progress_lock = threading.Lock()
processed_count = 0

# Track renamed files to handle duplicates
renamed_files = set()

def sanitize_filename(name):
    """Sanitize filename by removing/replacing invalid characters"""
    invalid_chars = '<>:"/\\|?*'
    for char in invalid_chars:
        name = name.replace(char, '_')
    # Remove multiple underscores and trim
    name = '_'.join(filter(None, name.split('_')))
    return name.strip()

def get_unique_filename(base_name, extension):
    """Get a unique filename, adding (1), (2), etc. if needed"""
    counter = 1
    original_name = f"{base_name}{extension}"
    current_name = original_name
    
    while current_name in renamed_files:
        current_name = f"{base_name} ({counter}){extension}"
        counter += 1
    
    renamed_files.add(current_name)
    return current_name

def is_already_renamed(filename):
    """Check if file is already renamed (contains version pattern)"""
    return ' v' in filename and (filename.endswith('.apk') or filename.endswith('.ipa'))

def extract_metadata_from_filename(filename):
    """Extract app name and version from already renamed files"""
    if not is_already_renamed(filename):
        return None, None
    
    # Pattern: AppName v1.0.apk/ipa
    match = re.match(r'(.+?)\s+v(.+?)\.(apk|ipa)$', filename)
    if match:
        app_name = match.group(1)
        version = match.group(2)
        return app_name, version
    return None, None

def extract_apk_icon(file_path, package, target_filename):
    """Extract highest quality icon from APK"""
    try:
        # Get all drawable resources
        result_resources = subprocess.check_output(
            ["aapt", "dump", "resources", file_path],
            stderr=subprocess.STDOUT,
            text=True,
            timeout=15
        )
        
        # Find all icon files in res/ folders
        icon_files = []
        for line in result_resources.splitlines():
            if 'drawable' in line and '.png' in line:
                # Extract the resource path
                parts = line.split()
                for part in parts:
                    if 'drawable' in part and '.png' in part:
                        icon_files.append(part)
        
        if icon_files:
            # Find the highest resolution 1:1 icon
            best_icon = None
            best_size = 0
            
            for icon_file in icon_files:
                # Look for common high-res icon patterns
                if any(pattern in icon_file.lower() for pattern in ['xxxhdpi', 'xxhdpi', 'xhdpi', 'hdpi']):
                    # Extract size from filename if possible
                    size_match = None
                    for pattern in ['xxxhdpi', 'xxhdpi', 'xhdpi', 'hdpi']:
                        if pattern in icon_file.lower():
                            size_match = pattern
                            break
                    
                    if size_match:
                        size_value = {'hdpi': 1, 'xhdpi': 2, 'xxhdpi': 3, 'xxxhdpi': 4}[size_match]
                        if size_value > best_size:
                            best_size = size_value
                            best_icon = icon_file
            
            if best_icon:
                icon_dest = os.path.join(icons_dir, f"{os.path.splitext(target_filename)[0]}.png")
                subprocess.run(
                    ["aapt", "d", "resources", file_path, best_icon, "-o", icon_dest],
                    stderr=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    timeout=10
                )
    except Exception as e:
        logging.warning(f"Failed to extract APK icon for {file_path}: {e}")

def extract_ipa_icon(file_path, target_filename):
    """Extract highest quality icon from IPA"""
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            with zipfile.ZipFile(file_path, 'r') as zip_ref:
                # Find all icon files in the app bundle
                icon_files = []
                for file_info in zip_ref.infolist():
                    if file_info.filename.endswith('.png'):
                        filename_lower = file_info.filename.lower()
                        # Look for app icons with various naming patterns
                        if any(pattern in filename_lower for pattern in [
                            'appicon', 'icon', 'app_icon', 'applicationicon'
                        ]):
                            icon_files.append(file_info)
                
                if icon_files:
                    # Find the highest resolution icon
                    best_icon = None
                    best_resolution = 0
                    
                    for icon_info in icon_files:
                        filename = icon_info.filename.lower()
                        
                        # Extract resolution from filename patterns like AppIcon76x76@2x~ipad.png
                        resolution_match = re.search(r'(\d+)x(\d+)', filename)
                        if resolution_match:
                            width = int(resolution_match.group(1))
                            height = int(resolution_match.group(2))
                            resolution = width * height
                            
                            # Prefer square icons (1:1 ratio)
                            if width == height and resolution > best_resolution:
                                best_resolution = resolution
                                best_icon = icon_info
                        else:
                            # Fallback: use file size as resolution indicator
                            if icon_info.file_size > best_resolution:
                                best_resolution = icon_info.file_size
                                best_icon = icon_info
                    
                    if best_icon:
                        zip_ref.extract(best_icon.filename, temp_dir)
                        icon_dest = os.path.join(icons_dir, f"{os.path.splitext(target_filename)[0]}.png")
                        shutil.copy2(os.path.join(temp_dir, best_icon.filename), icon_dest)
    except Exception as e:
        logging.warning(f"Failed to extract IPA icon for {file_path}: {e}")

def process_file_metadata(file_path):
    """Process a single file and return metadata (without renaming)"""
    global processed_count
    
    try:
        file_size_mb = round(os.path.getsize(file_path) / (1024 * 1024), 2)
        
        # Check if already renamed
        already_renamed = is_already_renamed(file_path)
        if already_renamed:
            app_name, version = extract_metadata_from_filename(file_path)
            if app_name and version:
                with progress_lock:
                    processed_count += 1
                    if processed_count % 10 == 0:
                        print(f"Processed {processed_count} files...")
                
                return {
                    'file': file_path,
                    'label': app_name,
                    'package': '',
                    'version': version,
                    'size_mb': file_size_mb,
                    'status': 'valid'
                }
        
        # Try APK processing first
        if file_path.endswith('.apk'):
            try:
                result = subprocess.check_output(
                    ["aapt", "dump", "badging", file_path],
                    stderr=subprocess.STDOUT,
                    text=True,
                    timeout=20
                )
                
                label = ""
                package = ""
                version = ""
                
                for line in result.splitlines():
                    if line.startswith("package:"):
                        for part in line.split():
                            if part.startswith("name="):
                                package = part.split("=")[1].strip("'")
                            elif part.startswith("versionName="):
                                version = part.split("=")[1].strip("'")
                    elif line.startswith("application-label:"):
                        label = line.split(":", 1)[1].strip("'")
                
                with progress_lock:
                    processed_count += 1
                    if processed_count % 10 == 0:
                        print(f"Processed {processed_count} files...")
                
                return {
                    'file': file_path,
                    'label': label,
                    'package': package,
                    'version': version,
                    'size_mb': file_size_mb,
                    'status': 'valid'
                }
                
            except subprocess.CalledProcessError:
                # Try as IPA file (might be misnamed)
                return process_ipa_metadata(file_path, file_size_mb)
        
        elif file_path.endswith('.ipa'):
            return process_ipa_metadata(file_path, file_size_mb)
            
    except Exception as e:
        logging.error(f"Error processing {file_path}: {str(e)}")
        return {
            'file': file_path,
            'label': 'invalid',
            'package': '',
            'version': '',
            'size_mb': file_size_mb,
            'status': 'invalid'
        }

def process_ipa_metadata(file_path, file_size_mb):
    """Process IPA file metadata"""
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            with zipfile.ZipFile(file_path, 'r') as zip_ref:
                # Find all Info.plist files
                info_files = [f for f in zip_ref.namelist() if f.endswith('Info.plist')]
                
                if not info_files:
                    logging.warning(f"No Info.plist found in {file_path}")
                    return {
                        'file': file_path,
                        'label': 'invalid',
                        'package': '',
                        'version': '',
                        'size_mb': file_size_mb,
                        'status': 'invalid'
                    }
                
                # Try to find the main app's Info.plist (usually in Payload/*.app/)
                main_info_file = None
                for info_file in info_files:
                    if ('Payload' in info_file and info_file.endswith('Info.plist') and 
                        '.app/' in info_file and not any(x in info_file for x in [
                            '.bundle/', '.framework/', '.storyboardc/', 'GoogleService-Info.plist'
                        ])):
                        main_info_file = info_file
                        break
                
                if not main_info_file:
                    # Fallback: look for any Info.plist in .app/ directory
                    for info_file in info_files:
                        if '.app/' in info_file and info_file.endswith('Info.plist'):
                            main_info_file = info_file
                            break
                
                if not main_info_file:
                    main_info_file = info_files[0]  # Last resort fallback
                
                logging.info(f"Using Info.plist: {main_info_file}")
                zip_ref.extract(main_info_file, temp_dir)
                
                info_path = os.path.join(temp_dir, main_info_file)
                
                try:
                    with open(info_path, 'rb') as fp:
                        info_plist = plistlib.load(fp)
                except Exception as e:
                    logging.error(f"Failed to parse Info.plist for {file_path}: {e}")
                    return {
                        'file': file_path,
                        'label': 'invalid',
                        'package': '',
                        'version': '',
                        'size_mb': file_size_mb,
                        'status': 'invalid'
                    }
                
                # Try multiple possible keys for app name
                label = (info_plist.get('CFBundleDisplayName') or 
                        info_plist.get('CFBundleName') or 
                        info_plist.get('CFBundleExecutable') or 
                        info_plist.get('CFBundleDisplayNameLocalized') or '')
                
                # Try multiple possible keys for version
                version = (info_plist.get('CFBundleShortVersionString') or 
                          info_plist.get('CFBundleVersion') or '')
                
                package = info_plist.get('CFBundleIdentifier', '')
                
                # Debug logging
                logging.info(f"IPA {file_path}: label='{label}', package='{package}', version='{version}'")
                
                with progress_lock:
                    processed_count += 1
                    if processed_count % 10 == 0:
                        print(f"Processed {processed_count} files...")
                
                return {
                    'file': file_path,
                    'label': label,
                    'package': package,
                    'version': version,
                    'size_mb': file_size_mb,
                    'status': 'valid'
                }
                
    except Exception as e:
        logging.error(f"Error processing IPA {file_path}: {str(e)}")
        return {
            'file': file_path,
            'label': 'invalid',
            'package': '',
            'version': '',
            'size_mb': file_size_mb,
            'status': 'invalid'
        }

def main():
    start_time = time.time()
    
    # Get all APK and IPA files
    files_to_process = []
    for f in os.listdir("."):
        if f.endswith(".apk") or f.endswith(".ipa"):
            files_to_process.append(f)
    
    print(f"Found {len(files_to_process)} files to process")
    print(f"Using {cpu_count()} CPU cores for parallel processing")
    
    # Process files in parallel (metadata extraction only)
    invalid_files = []
    valid_count = 0
    processing_results = []
    
    # Use ProcessPoolExecutor for CPU-bound tasks
    with ProcessPoolExecutor(max_workers=cpu_count()) as executor:
        # Submit all tasks
        future_to_file = {executor.submit(process_file_metadata, f): f for f in files_to_process}
        
        # Process completed tasks
        for future in as_completed(future_to_file):
            file = future_to_file[future]
            try:
                result = future.result()
                processing_results.append(result)
                
                if result['status'] == 'invalid':
                    invalid_files.append(result['file'])
                else:
                    valid_count += 1
                    
            except Exception as e:
                logging.error(f"Failed to process {file}: {str(e)}")
                invalid_files.append(file)
                processing_results.append({
                    'file': file, 'label': 'invalid', 'package': '', 
                    'version': '', 'size_mb': 0, 'status': 'invalid'
                })
    
    # Wait a moment for all parallel processes to finish
    time.sleep(1)
    
    # Now rename files sequentially to avoid conflicts
    print("Renaming files...")
    rename_results = []
    used_names = set()  # Track used names locally
    
    for result in processing_results:
        if result['status'] == 'valid' and not is_already_renamed(result['file']):
            try:
                # Create new filename
                app_name = result['label'] if result['label'] and result['label'].strip() else result['package']
                if not app_name or not app_name.strip():
                    if result['package'] and result['package'].strip():
                        parts = result['package'].split('.')
                        if len(parts) > 1:
                            app_name = parts[-1].replace('_', ' ').title()
                        else:
                            app_name = result['package'].replace('_', ' ').title()
                    else:
                        app_name = os.path.splitext(result['file'])[0]
                
                app_name = app_name.strip()
                if not app_name:
                    app_name = f"App_{os.path.splitext(result['file'])[0]}"
                
                safe_name = sanitize_filename(app_name)
                if result['version'] and result['version'].strip():
                    safe_name = f"{safe_name} v{result['version']}"
                else:
                    safe_name = f"{safe_name} v1.0"
                
                extension = ".apk" if result['file'].endswith('.apk') else ".ipa"
                
                # Generate unique filename
                counter = 1
                original_name = f"{safe_name}{extension}"
                new_filename = original_name
                
                while new_filename in used_names:
                    new_filename = f"{safe_name} ({counter}){extension}"
                    counter += 1
                
                used_names.add(new_filename)
                
                # Rename the file with retry logic
                if result['file'] != new_filename:
                    max_retries = 5
                    for attempt in range(max_retries):
                        try:
                            os.rename(result['file'], new_filename)
                            result['file'] = new_filename
                            logging.info(f"Renamed to {new_filename}")
                            break
                        except (OSError, PermissionError) as e:
                            if attempt < max_retries - 1:
                                time.sleep(0.2)  # Wait 200ms before retry
                                logging.warning(f"Retry {attempt + 1} for renaming {result['file']}: {e}")
                            else:
                                logging.error(f"Failed to rename {result['file']} after {max_retries} attempts: {e}")
                                # Mark as invalid if we can't rename
                                result['status'] = 'invalid'
                
            except Exception as e:
                logging.error(f"Failed to rename {result['file']}: {e}")
        
        rename_results.append(result)
    
    # Extract icons for renamed files
    print("Extracting icons...")
    for result in rename_results:
        if result['status'] == 'valid':
            try:
                if result['file'].endswith('.apk') and result['package']:
                    extract_apk_icon(result['file'], result['package'], result['file'])
                elif result['file'].endswith('.ipa'):
                    extract_ipa_icon(result['file'], result['file'])
            except Exception as e:
                logging.warning(f"Failed to extract icon for {result['file']}: {e}")
    
    # Write results to CSV
    with open("apk_list.csv", "w", newline="", encoding="utf-8") as out:
        w = csv.writer(out, delimiter='|')
        w.writerow(["file", "label", "package", "version", "size_mb"])
        
        for result in rename_results:
            w.writerow([result['file'], result['label'], result['package'], 
                      result['version'], result['size_mb']])
    
    end_time = time.time()
    processing_time = round(end_time - start_time, 2)
    
    print(f"\nDone in {processing_time} seconds")
    print(f"Processed {len(files_to_process)} total files")
    print(f"Valid files: {valid_count}")
    print(f"Invalid files: {len(invalid_files)}")
    print(f"Processing rate: {len(files_to_process)/processing_time:.1f} files/second")
    
    logging.info(f"Processing completed in {processing_time} seconds. "
                f"{len(files_to_process)} total files, {valid_count} valid, {len(invalid_files)} invalid.")
    
    if invalid_files:
        print("\nInvalid files:")
        for f in invalid_files:
            print(f"  - {f}")
    
    # Final cleanup of any invalid icons that might have been created
    cleanup_invalid_icons()

if __name__ == "__main__":
    main()
