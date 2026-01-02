import os
import zipfile
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path
import subprocess
import tempfile

def extract_icons_from_apks(input_dir='.', output_dir='./out/'):
    """
    Extract the main launcher icons from all APK files in the input directory.
    This extracts the actual icon that appears during installation by parsing the AndroidManifest.xml.
    """
    # Create output directory if it doesn't exist
    os.makedirs(output_dir, exist_ok=True)
    
    # Find all APK files in the input directory
    apk_files = [f for f in os.listdir(input_dir) if f.lower().endswith('.apk')]
    
    if not apk_files:
        print("No APK files found in the directory.")
        return
    
    print(f"Found {len(apk_files)} APK files. Extracting icons...")
    
    for apk_file in apk_files:
        try:
            apk_path = os.path.join(input_dir, apk_file)
            app_name = os.path.splitext(apk_file)[0]
            
            # Open the APK as a ZIP file
            with zipfile.ZipFile(apk_path, 'r') as zip_ref:
                # First, extract the AndroidManifest.xml to find the main icon reference
                if 'AndroidManifest.xml' not in zip_ref.namelist():
                    print(f"No AndroidManifest.xml found in {apk_file}")
                    continue
                
                # Create a temporary directory for extraction
                with tempfile.TemporaryDirectory() as temp_dir:
                    # Extract AndroidManifest.xml to the temporary directory
                    temp_manifest_path = os.path.join(temp_dir, "AndroidManifest.xml")
                    with zip_ref.open('AndroidManifest.xml', 'r') as manifest_file, open(temp_manifest_path, 'wb') as temp_file:
                        shutil.copyfileobj(manifest_file, temp_file)
                    
                    # Try to use aapt to dump the manifest (requires Android SDK tools)
                    icon_resource_id = None
                    try:
                        # Try to use aapt to dump the manifest info
                        result = subprocess.run(
                            ['aapt', 'dump', 'badging', apk_path], 
                            capture_output=True, 
                            text=True, 
                            check=False
                        )
                        
                        if result.returncode == 0:
                            # Parse the output to find the application icon
                            for line in result.stdout.splitlines():
                                if 'application-icon' in line:
                                    # Extract the icon path from the output
                                    icon_path = line.split("'")[1]
                                    icon_resource_id = icon_path
                                    break
                        else:
                            print(f"aapt failed for {apk_file}, falling back to binary XML parsing")
                            
                    except (subprocess.SubprocessError, FileNotFoundError):
                        print(f"aapt not available for {apk_file}, falling back to alternative methods")
                    
                    # If aapt failed or isn't available, try alternative methods
                    if not icon_resource_id:
                        try:
                            # Try using a third-party binary XML parser like androguard if available
                            try:
                                from androguard.core.bytecodes.apk import APK
                                apk_obj = APK(apk_path)
                                icon_resource_id = apk_obj.get_app_icon()
                            except ImportError:
                                print(f"androguard not available for {apk_file}")
                                
                                # Fallback to simple string search in the binary file
                                # This is not reliable but might work in some cases
                                with open(temp_manifest_path, 'rb') as f:
                                    content = f.read()
                                    # Look for common icon strings in the binary content
                                    for icon_name in [b'ic_launcher', b'icon', b'logo']:
                                        if icon_name in content:
                                            icon_resource_id = icon_name.decode('utf-8')
                                            break
                        except Exception as e:
                            print(f"Error with alternative parsing for {apk_file}: {str(e)}")
                
                # If we found an icon reference, look for the corresponding resource
                if icon_resource_id:
                    # Look for the icon in common resource directories
                    icon_paths = []
                    for file_path in zip_ref.namelist():
                        if ('res/drawable' in file_path or 'res/mipmap' in file_path) and \
                           (file_path.endswith('.png') or file_path.endswith('.webp')):
                            # Extract the resource name without extension
                            resource_name = os.path.splitext(os.path.basename(file_path))[0]
                            if resource_name in icon_resource_id or icon_resource_id in resource_name:
                                icon_paths.append(file_path)
                else:
                    # Fallback: look for common launcher icon patterns
                    icon_paths = [f for f in zip_ref.namelist() if 
                                 ('res/drawable' in f or 'res/mipmap' in f) and 
                                 (f.endswith('.png') or f.endswith('.webp')) and
                                 ('ic_launcher' in f or 'icon' in f)]
                
                if not icon_paths:
                    print(f"No icons found in {apk_file}")
                    continue
                
                # Extract the highest resolution icons (usually in -xxxhdpi or -xxhdpi folders)
                for icon_path in sorted(icon_paths, key=lambda x: 
                                      ('xxxhdpi' in x) * 5 + 
                                      ('xxhdpi' in x) * 4 + 
                                      ('xhdpi' in x) * 3 + 
                                      ('hdpi' in x) * 2 + 
                                      ('mdpi' in x) * 1,
                                      reverse=True):
                    icon_filename = os.path.basename(icon_path)
                    output_path = os.path.join(output_dir, f"{app_name}_{icon_filename}")
                    
                    # Extract the icon
                    with zip_ref.open(icon_path) as source, open(output_path, 'wb') as target:
                        shutil.copyfileobj(source, target)
                    
                    print(f"Extracted icon from {apk_file} to {output_path}")
                    # Only extract the highest resolution icon for each app
                    break
        
        except Exception as e:
            print(f"Error processing {apk_file}: {str(e)}")
    
    print(f"Icon extraction complete. Icons saved to {output_dir}")

if __name__ == "__main__":
    extract_icons_from_apks()
