import zipfile
import plistlib
import os
import tempfile

def debug_ipa_file(file_path):
    """Debug function to check what's in an IPA file's Info.plist"""
    print(f"Debugging IPA file: {file_path}")
    
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            with zipfile.ZipFile(file_path, 'r') as zip_ref:
                # Find all Info.plist files
                info_files = [f for f in zip_ref.namelist() if f.endswith('Info.plist')]
                print(f"Found {len(info_files)} Info.plist files:")
                for info_file in info_files:
                    print(f"  - {info_file}")
                
                if info_files:
                    # Find the main app's Info.plist (usually in Payload/*.app/)
                    main_info_file = None
                    for info_file in info_files:
                        if 'Payload' in info_file and info_file.endswith('Info.plist') and '.app/' in info_file:
                            # Make sure it's not in a bundle or framework
                            if not any(x in info_file for x in ['.bundle/', '.framework/', '.storyboardc/']):
                                main_info_file = info_file
                                break
                    
                    if not main_info_file:
                        main_info_file = info_files[0]  # Fallback to first found
                    
                    print(f"Using Info.plist: {main_info_file}")
                    zip_ref.extract(main_info_file, temp_dir)
                    info_path = os.path.join(temp_dir, main_info_file)
                    
                    with open(info_path, 'rb') as fp:
                        info_plist = plistlib.load(fp)
                    
                    print("\nInfo.plist contents:")
                    for key, value in info_plist.items():
                        if any(keyword in key.lower() for keyword in ['name', 'version', 'bundle', 'display']):
                            print(f"  {key}: {value}")
                    
                    # Try to extract metadata
                    label = (info_plist.get('CFBundleDisplayName') or 
                            info_plist.get('CFBundleName') or 
                            info_plist.get('CFBundleExecutable') or 
                            info_plist.get('CFBundleDisplayNameLocalized') or '')
                    
                    version = (info_plist.get('CFBundleShortVersionString') or 
                              info_plist.get('CFBundleVersion') or '')
                    
                    package = info_plist.get('CFBundleIdentifier', '')
                    
                    print(f"\nExtracted metadata:")
                    print(f"  Label: '{label}'")
                    print(f"  Package: '{package}'")
                    print(f"  Version: '{version}'")
                    
                    return label, package, version
                else:
                    print("No Info.plist files found!")
                    return None, None, None
                    
    except Exception as e:
        print(f"Error processing {file_path}: {e}")
        return None, None, None

if __name__ == "__main__":
    # Test with a specific IPA file
    test_file = "1000.ipa"  # Replace with an actual IPA file name
    if os.path.exists(test_file):
        debug_ipa_file(test_file)
    else:
        print(f"File {test_file} not found")
