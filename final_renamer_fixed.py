import os, subprocess, csv, zipfile, plistlib, shutil, time, logging, re, json
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed
from multiprocessing import cpu_count
import tempfile
import threading

# Set up logging
logging.basicConfig(filename="app_renaming_fixed.log", level=logging.INFO, 
                   format='%(asctime)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')

# Create icons directory if it doesn't exist
icons_dir = "icons"
os.makedirs(icons_dir, exist_ok=True)

def sanitize_filename(name):
    """Sanitize filename by removing/replacing invalid characters"""
    invalid_chars = '<>:"/\\|?*'
    for char in invalid_chars:
        name = name.replace(char, '_')
    # Remove multiple underscores and trim
    name = '_'.join(filter(None, name.split('_')))
    return name.strip()

def extract_apk_metadata(file_path):
    """Extract APK metadata using comprehensive analysis"""
    try:
        result = subprocess.check_output(
            ["aapt", "dump", "badging", file_path],
            stderr=subprocess.STDOUT,
            text=True,
            timeout=30
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
        
        return {
            'name': label,
            'version': version,
            'package': package,
            'confidence': 3 if label and package else 1
        }
        
    except Exception as e:
        logging.error(f"Failed to extract APK metadata from {file_path}: {e}")
        return None

def extract_ipa_metadata(file_path):
    """Extract IPA metadata using comprehensive analysis"""
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            with zipfile.ZipFile(file_path, 'r') as zip_ref:
                # Find all Info.plist files
                info_files = [f for f in zip_ref.namelist() if f.endswith('Info.plist')]
                
                if not info_files:
                    return None
                
                # Find main app Info.plist
                main_info_file = None
                for info_file in info_files:
                    if ('Payload' in info_file and info_file.endswith('Info.plist') and 
                        '.app/' in info_file and not any(x in info_file for x in [
                            '.bundle/', '.framework/', '.storyboardc/', 'GoogleService-Info.plist'
                        ])):
                        main_info_file = info_file
                        break
                
                if not main_info_file:
                    for info_file in info_files:
                        if '.app/' in info_file and info_file.endswith('Info.plist'):
                            main_info_file = info_file
                            break
                
                if not main_info_file:
                    main_info_file = info_files[0]
                
                # Extract and analyze main Info.plist
                zip_ref.extract(main_info_file, temp_dir)
                info_path = os.path.join(temp_dir, main_info_file)
                
                with open(info_path, 'rb') as fp:
                    info_plist = plistlib.load(fp)
                
                # Extract metadata with priority order
                name = (info_plist.get('CFBundleDisplayName') or 
                       info_plist.get('CFBundleName') or 
                       info_plist.get('CFBundleExecutable') or '')
                
                version = (info_plist.get('CFBundleShortVersionString') or 
                          info_plist.get('CFBundleVersion') or '')
                
                package = info_plist.get('CFBundleIdentifier', '')
                
                confidence = 4 if info_plist.get('CFBundleDisplayName') else 3 if info_plist.get('CFBundleName') else 2
                
                return {
                    'name': name,
                    'version': version,
                    'package': package,
                    'confidence': confidence
                }
                
    except Exception as e:
        logging.error(f"Failed to extract IPA metadata from {file_path}: {e}")
        return None

def extract_apk_icon(file_path, package, target_filename):
    """Extract highest quality icon from APK"""
    try:
        result_resources = subprocess.check_output(
            ["aapt", "dump", "resources", file_path],
            stderr=subprocess.STDOUT,
            text=True,
            timeout=15
        )
        
        icon_files = []
        for line in result_resources.splitlines():
            if 'drawable' in line and '.png' in line:
                parts = line.split()
                for part in parts:
                    if 'drawable' in part and '.png' in part:
                        icon_files.append(part)
        
        if icon_files:
            best_icon = None
            best_size = 0
            
            for icon_file in icon_files:
                if any(pattern in icon_file.lower() for pattern in ['xxxhdpi', 'xxhdpi', 'xhdpi', 'hdpi']):
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
                icon_files = []
                for file_info in zip_ref.infolist():
                    if file_info.filename.endswith('.png'):
                        filename_lower = file_info.filename.lower()
                        if any(pattern in filename_lower for pattern in [
                            'appicon', 'icon', 'app_icon', 'applicationicon'
                        ]):
                            icon_files.append(file_info)
                
                if icon_files:
                    best_icon = None
                    best_resolution = 0
                    
                    for icon_info in icon_files:
                        filename = icon_info.filename.lower()
                        
                        resolution_match = re.search(r'(\d+)x(\d+)', filename)
                        if resolution_match:
                            width = int(resolution_match.group(1))
                            height = int(resolution_match.group(2))
                            resolution = width * height
                            
                            if width == height and resolution > best_resolution:
                                best_resolution = resolution
                                best_icon = icon_info
                        else:
                            if icon_info.file_size > best_resolution:
                                best_resolution = icon_info.file_size
                                best_icon = icon_info
                    
                    if best_icon:
                        zip_ref.extract(best_icon.filename, temp_dir)
                        icon_dest = os.path.join(icons_dir, f"{os.path.splitext(target_filename)[0]}.png")
                        shutil.copy2(os.path.join(temp_dir, best_icon.filename), icon_dest)
    except Exception as e:
        logging.warning(f"Failed to extract IPA icon for {file_path}: {e}")

def process_file(file_path):
    """Process a single file and return metadata"""
    try:
        file_size_mb = round(os.path.getsize(file_path) / (1024 * 1024), 2)
        
        if file_path.endswith('.apk'):
            metadata = extract_apk_metadata(file_path)
        elif file_path.endswith('.ipa'):
            metadata = extract_ipa_metadata(file_path)
        else:
            return None
        
        if not metadata:
            return {
                'file': file_path,
                'name': '',
                'version': '',
                'package': '',
                'size_mb': file_size_mb,
                'confidence': 0,
                'status': 'invalid'
            }
        
        return {
            'file': file_path,
            'name': metadata['name'],
            'version': metadata['version'],
            'package': metadata['package'],
            'size_mb': file_size_mb,
            'confidence': metadata['confidence'],
            'status': 'valid'
        }
        
    except Exception as e:
        logging.error(f"Error processing {file_path}: {e}")
        return {
            'file': file_path,
            'name': '',
            'version': '',
            'package': '',
            'size_mb': 0,
            'confidence': 0,
            'status': 'invalid'
        }

def get_unique_filename(base_name, extension, existing_files):
    """Get a unique filename, checking against existing files"""
    counter = 1
    original_name = f"{base_name}{extension}"
    new_filename = original_name
    
    while new_filename in existing_files:
        new_filename = f"{base_name} ({counter}){extension}"
        counter += 1
    
    return new_filename

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
    processing_results = []
    
    with ProcessPoolExecutor(max_workers=cpu_count()) as executor:
        future_to_file = {executor.submit(process_file, f): f for f in files_to_process}
        
        for future in as_completed(future_to_file):
            file = future_to_file[future]
            try:
                result = future.result()
                if result:
                    processing_results.append(result)
                    if result['confidence'] >= 3:
                        print(f"✓ {file}: {result['name']} v{result['version']} (confidence: {result['confidence']})")
                    elif result['confidence'] >= 1:
                        print(f"⚠ {file}: {result['name']} v{result['version']} (confidence: {result['confidence']})")
                    else:
                        print(f"✗ {file}: No metadata found")
            except Exception as e:
                logging.error(f"Failed to process {file}: {str(e)}")
    
    # Wait for all processes to finish
    time.sleep(1)
    
    # Get all existing files in directory to avoid conflicts
    existing_files = set()
    for f in os.listdir("."):
        if f.endswith(".apk") or f.endswith(".ipa"):
            existing_files.add(f)
    
    # Now rename files sequentially
    print("\nRenaming files...")
    rename_results = []
    
    for result in processing_results:
        if result['status'] == 'valid' and result['confidence'] >= 1:
            try:
                # Create new filename with better fallback strategies
                app_name = result['name']
                if not app_name or not app_name.strip():
                    # Use package name as fallback
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
                new_filename = get_unique_filename(safe_name, extension, existing_files)
                existing_files.add(new_filename)  # Add to set to prevent future conflicts
                
                # Rename the file
                if result['file'] != new_filename:
                    max_retries = 5
                    for attempt in range(max_retries):
                        try:
                            os.rename(result['file'], new_filename)
                            result['file'] = new_filename
                            logging.info(f"Renamed to {new_filename}")
                            print(f"  → Renamed to {new_filename}")
                            break
                        except (OSError, PermissionError) as e:
                            if attempt < max_retries - 1:
                                time.sleep(0.2)
                                logging.warning(f"Retry {attempt + 1} for renaming {result['file']}: {e}")
                            else:
                                logging.error(f"Failed to rename {result['file']} after {max_retries} attempts: {e}")
                                result['status'] = 'invalid'
                
            except Exception as e:
                logging.error(f"Failed to rename {result['file']}: {e}")
        
        rename_results.append(result)
    
    # Extract icons for renamed files
    print("\nExtracting icons...")
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
    with open("app_list_final_fixed.csv", "w", newline="", encoding="utf-8") as out:
        w = csv.writer(out, delimiter='|')
        w.writerow(["file", "name", "package", "version", "size_mb", "confidence"])
        
        for result in rename_results:
            w.writerow([
                result['file'],
                result['name'],
                result['package'],
                result['version'],
                result['size_mb'],
                result['confidence']
            ])
    
    # Statistics
    total_files = len(rename_results)
    valid_files = len([r for r in rename_results if r['status'] == 'valid'])
    high_confidence = len([r for r in rename_results if r['confidence'] >= 3])
    renamed_files = len([r for r in rename_results if r['file'] != os.path.basename(r['file'])])
    
    end_time = time.time()
    processing_time = round(end_time - start_time, 2)
    
    print(f"\n" + "="*60)
    print(f"PROCESSING COMPLETED")
    print(f"="*60)
    print(f"Total time: {processing_time} seconds")
    print(f"Total files: {total_files}")
    print(f"Valid files: {valid_files}")
    print(f"High confidence (3+): {high_confidence}")
    print(f"Files renamed: {renamed_files}")
    print(f"Processing rate: {total_files/processing_time:.1f} files/second")
    
    # Show low confidence files
    low_conf_files = [r for r in rename_results if r['confidence'] < 1]
    if low_conf_files:
        print(f"\nFiles with low confidence ({len(low_conf_files)}):")
        for result in low_conf_files[:10]:
            print(f"  - {result['file']}")
        if len(low_conf_files) > 10:
            print(f"  ... and {len(low_conf_files) - 10} more")

if __name__ == "__main__":
    main()
