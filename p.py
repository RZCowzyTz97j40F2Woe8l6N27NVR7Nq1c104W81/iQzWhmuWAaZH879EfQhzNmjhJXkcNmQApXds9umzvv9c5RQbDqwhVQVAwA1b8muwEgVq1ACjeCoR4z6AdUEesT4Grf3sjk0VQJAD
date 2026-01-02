import os, subprocess, csv, zipfile, plistlib, shutil, time, logging
from pathlib import Path

# Set up logging
logging.basicConfig(filename="app_processing.log", level=logging.INFO, 
                   format='%(asctime)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')

# Create icons directory if it doesn't exist
icons_dir = "icons"
os.makedirs(icons_dir, exist_ok=True)

start_time = time.time()
invalid_files = []

out = open("apk_list.csv", "w", newline="", encoding="utf-8")
w = csv.writer(out, delimiter='|')
w.writerow(["file", "label", "package", "version", "size_mb"])

for f in os.listdir("."):
    if f.endswith(".apk") or f.endswith(".ipa"):
        file_size_mb = round(os.path.getsize(f) / (1024 * 1024), 2)
        file_ext = os.path.splitext(f)[1].lower()
        
        if file_ext == ".apk":
            try:
                result = subprocess.check_output(
                    ["aapt", "dump", "badging", f],
                    stderr=subprocess.STDOUT,
                    text=True
                )
                label = ""
                package = ""
                version = ""
                icon_path = None
                
                for line in result.splitlines():
                    if line.startswith("package:"):
                        for part in line.split():
                            if part.startswith("name="):
                                package = part.split("=")[1].strip("'")
                            elif part.startswith("versionName="):
                                version = part.split("=")[1].strip("'")
                    elif line.startswith("application-label:"):
                        label = line.split(":", 1)[1].strip("'")
                    elif line.startswith("application-icon-") or line.startswith("icon:"):
                        icon_path = line.split(":", 1)[1].strip("'")
                
                # Extract icon if found
                if icon_path:
                    icon_dest = os.path.join(icons_dir, f"{package}.png")
                    try:
                        subprocess.run(
                            ["aapt", "d", "resources", f, icon_path, "-o", icon_dest],
                            stderr=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL
                        )
                    except Exception as e:
                        logging.warning(f"Failed to extract icon for {f}: {e}")
                
                w.writerow([f, label, package, version, file_size_mb])
            except subprocess.CalledProcessError:
                # Try as IPA file (might be misnamed)
                try:
                    temp_dir = "temp_extract"
                    if os.path.exists(temp_dir):
                        shutil.rmtree(temp_dir)
                    os.makedirs(temp_dir)
                    
                    with zipfile.ZipFile(f, 'r') as zip_ref:
                        zip_ref.extractall(temp_dir)
                    
                    # Find the .app directory in Payload folder
                    payload_dir = os.path.join(temp_dir, "Payload")
                    if os.path.exists(payload_dir):
                        app_folders = [d for d in os.listdir(payload_dir) if d.endswith(".app")]
                        if app_folders:
                            app_path = os.path.join(payload_dir, app_folders[0])
                            info_plist_path = os.path.join(app_path, "Info.plist")
                            
                            if os.path.exists(info_plist_path):
                                with open(info_plist_path, 'rb') as fp:
                                    info_plist = plistlib.load(fp)
                                    
                                label = info_plist.get('CFBundleDisplayName', info_plist.get('CFBundleName', ''))
                                package = info_plist.get('CFBundleIdentifier', '')
                                version = info_plist.get('CFBundleShortVersionString', '')
                                
                                # Extract icon
                                try:
                                    # Look for app icons
                                    icon_files = []
                                    for root, dirs, files in os.walk(app_path):
                                        for file in files:
                                            if file.endswith('.png') and ('icon' in file.lower() or 'appicon' in file.lower()):
                                                icon_files.append(os.path.join(root, file))
                                    
                                    if icon_files:
                                        # Use the largest icon file
                                        largest_icon = max(icon_files, key=os.path.getsize)
                                        icon_dest = os.path.join(icons_dir, f"{package}.png")
                                        shutil.copy2(largest_icon, icon_dest)
                                except Exception as e:
                                    logging.warning(f"Failed to extract icon for {f}: {e}")
                                
                                # Rename file from .apk to .ipa if needed
                                if f.endswith('.apk'):
                                    new_name = f.replace('.apk', '.ipa')
                                    os.rename(f, new_name)
                                    w.writerow([new_name, label, package, version, file_size_mb])
                                else:
                                    w.writerow([f, label, package, version, file_size_mb])
                                
                                shutil.rmtree(temp_dir)
                                continue
                    
                    shutil.rmtree(temp_dir)
                    invalid_files.append(f)
                    w.writerow([f, "invalid", "", "", file_size_mb])
                    logging.warning(f"Invalid file: {f}")
                except Exception as e:
                    if os.path.exists(temp_dir):
                        shutil.rmtree(temp_dir)
                    invalid_files.append(f)
                    w.writerow([f, "invalid", "", "", file_size_mb])
                    logging.error(f"Error processing {f}: {str(e)}")
        else:  # .ipa file
            try:
                temp_dir = "temp_extract"
                if os.path.exists(temp_dir):
                    shutil.rmtree(temp_dir)
                os.makedirs(temp_dir)
                
                with zipfile.ZipFile(f, 'r') as zip_ref:
                    zip_ref.extractall(temp_dir)
                
                # Find the .app directory in Payload folder
                payload_dir = os.path.join(temp_dir, "Payload")
                if os.path.exists(payload_dir):
                    app_folders = [d for d in os.listdir(payload_dir) if d.endswith(".app")]
                    if app_folders:
                        app_path = os.path.join(payload_dir, app_folders[0])
                        info_plist_path = os.path.join(app_path, "Info.plist")
                        
                        if os.path.exists(info_plist_path):
                            with open(info_plist_path, 'rb') as fp:
                                info_plist = plistlib.load(fp)
                                
                            label = info_plist.get('CFBundleDisplayName', info_plist.get('CFBundleName', ''))
                            package = info_plist.get('CFBundleIdentifier', '')
                            version = info_plist.get('CFBundleShortVersionString', '')
                            
                            # Extract icon
                            try:
                                # Look for app icons
                                icon_files = []
                                for root, dirs, files in os.walk(app_path):
                                    for file in files:
                                        if file.endswith('.png') and ('icon' in file.lower() or 'appicon' in file.lower()):
                                            icon_files.append(os.path.join(root, file))
                                
                                if icon_files:
                                    # Use the largest icon file
                                    largest_icon = max(icon_files, key=os.path.getsize)
                                    icon_dest = os.path.join(icons_dir, f"{package}.png")
                                    shutil.copy2(largest_icon, icon_dest)
                            except Exception as e:
                                logging.warning(f"Failed to extract icon for {f}: {e}")
                            
                            w.writerow([f, label, package, version, file_size_mb])
                            
                            shutil.rmtree(temp_dir)
                            continue
                
                shutil.rmtree(temp_dir)
                invalid_files.append(f)
                w.writerow([f, "invalid", "", "", file_size_mb])
                logging.warning(f"Invalid file: {f}")
            except Exception as e:
                if os.path.exists(temp_dir):
                    shutil.rmtree(temp_dir)
                invalid_files.append(f)
                w.writerow([f, "invalid", "", "", file_size_mb])
                logging.error(f"Error processing {f}: {str(e)}")

out.close()

end_time = time.time()
processing_time = round(end_time - start_time, 2)
print(f"Done in {processing_time} seconds")
print(f"Processed {len(invalid_files)} invalid files")
logging.info(f"Processing completed in {processing_time} seconds. {len(invalid_files)} invalid files.")
if invalid_files:
    print("Invalid files:")
    for f in invalid_files:
        print(f"  - {f}")
