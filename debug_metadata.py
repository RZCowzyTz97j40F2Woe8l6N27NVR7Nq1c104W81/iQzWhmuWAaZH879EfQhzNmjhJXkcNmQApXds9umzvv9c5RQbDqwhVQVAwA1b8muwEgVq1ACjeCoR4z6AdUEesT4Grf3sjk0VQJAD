import os, subprocess, zipfile, plistlib, tempfile, re
from pathlib import Path

def extract_apk_metadata_advanced(file_path):
    """Advanced APK metadata extraction using multiple methods"""
    print(f"\nAnalyzing APK: {file_path}")
    
    methods = {}
    
    # Method 1: aapt dump badging (standard)
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
        
        methods['aapt_badging'] = {
            'label': label,
            'package': package,
            'version': version
        }
        print(f"  aapt badging: '{label}' | '{package}' | '{version}'")
        
    except Exception as e:
        methods['aapt_badging'] = {'error': str(e)}
        print(f"  aapt badging: ERROR - {e}")
    
    # Method 2: aapt dump resources
    try:
        result = subprocess.check_output(
            ["aapt", "dump", "resources", file_path],
            stderr=subprocess.STDOUT,
            text=True,
            timeout=30
        )
        
        # Look for app name patterns
        app_name = ""
        for line in result.splitlines():
            if any(pattern in line.lower() for pattern in ['app_name', 'application_name', 'app_label']):
                if 'string' in line:
                    # Extract string value
                    parts = line.split()
                    for part in parts:
                        if 'app_name' in part.lower() or 'application_name' in part.lower():
                            app_name = part.split('=')[-1].strip('"\'')
                            break
        
        methods['aapt_resources'] = {'app_name': app_name}
        print(f"  aapt resources: '{app_name}'")
        
    except Exception as e:
        methods['aapt_resources'] = {'error': str(e)}
        print(f"  aapt resources: ERROR - {e}")
    
    # Method 3: Try to extract strings.xml
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            # Try to extract strings.xml
            subprocess.run(
                ["aapt", "dump", "resources", file_path, "--values"],
                stdout=open(os.path.join(temp_dir, "resources.txt"), "w"),
                stderr=subprocess.DEVNULL,
                timeout=20
            )
            
            resources_path = os.path.join(temp_dir, "resources.txt")
            if os.path.exists(resources_path):
                with open(resources_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                
                # Look for app name in strings
                app_name = ""
                for line in content.splitlines():
                    if 'app_name' in line.lower() or 'application_name' in line.lower():
                        # Extract the value
                        if '=' in line:
                            value = line.split('=')[-1].strip()
                            if value and value != '""':
                                app_name = value.strip('"\'')
                                break
                
                methods['strings_xml'] = {'app_name': app_name}
                print(f"  strings.xml: '{app_name}'")
                
    except Exception as e:
        methods['strings_xml'] = {'error': str(e)}
        print(f"  strings.xml: ERROR - {e}")
    
    return methods

def extract_ipa_metadata_advanced(file_path):
    """Advanced IPA metadata extraction using multiple methods"""
    print(f"\nAnalyzing IPA: {file_path}")
    
    methods = {}
    
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            with zipfile.ZipFile(file_path, 'r') as zip_ref:
                # Find all Info.plist files
                info_files = [f for f in zip_ref.namelist() if f.endswith('Info.plist')]
                print(f"  Found {len(info_files)} Info.plist files")
                
                # Analyze each Info.plist file
                for i, info_file in enumerate(info_files[:10]):  # Limit to first 10
                    try:
                        zip_ref.extract(info_file, temp_dir)
                        info_path = os.path.join(temp_dir, info_file)
                        
                        with open(info_path, 'rb') as fp:
                            plist_data = plistlib.load(fp)
                        
                        # Extract all relevant fields
                        name_fields = {
                            'CFBundleDisplayName': plist_data.get('CFBundleDisplayName', ''),
                            'CFBundleName': plist_data.get('CFBundleName', ''),
                            'CFBundleExecutable': plist_data.get('CFBundleExecutable', ''),
                            'CFBundleDisplayNameLocalized': plist_data.get('CFBundleDisplayNameLocalized', ''),
                            'CFBundleIdentifier': plist_data.get('CFBundleIdentifier', ''),
                            'CFBundleShortVersionString': plist_data.get('CFBundleShortVersionString', ''),
                            'CFBundleVersion': plist_data.get('CFBundleVersion', '')
                        }
                        
                        # Filter out empty values
                        non_empty_fields = {k: v for k, v in name_fields.items() if v}
                        
                        methods[f'plist_{i}'] = {
                            'file': info_file,
                            'fields': non_empty_fields
                        }
                        
                        print(f"  plist_{i} ({info_file}):")
                        for key, value in non_empty_fields.items():
                            print(f"    {key}: '{value}'")
                        
                    except Exception as e:
                        methods[f'plist_{i}'] = {'error': str(e)}
                        print(f"  plist_{i}: ERROR - {e}")
                
                # Try plutil if available
                try:
                    main_plist = None
                    for info_file in info_files:
                        if '.app/' in info_file and info_file.endswith('Info.plist'):
                            main_plist = info_file
                            break
                    
                    if main_plist:
                        zip_ref.extract(main_plist, temp_dir)
                        plist_path = os.path.join(temp_dir, main_plist)
                        
                        plutil_result = subprocess.check_output(
                            ["plutil", "-p", plist_path],
                            stderr=subprocess.STDOUT,
                            text=True,
                            timeout=10
                        )
                        
                        methods['plutil'] = {'output': plutil_result}
                        print(f"  plutil: Successfully parsed {main_plist}")
                        
                except Exception as e:
                    methods['plutil'] = {'error': str(e)}
                    print(f"  plutil: ERROR - {e}")
    
    except Exception as e:
        methods['error'] = str(e)
        print(f"  General error: {e}")
    
    return methods

def analyze_problematic_files():
    """Analyze files that are likely to have naming issues"""
    
    # Get files that might be problematic
    apk_files = [f for f in os.listdir(".") if f.endswith('.apk')]
    ipa_files = [f for f in os.listdir(".") if f.endswith('.ipa')]
    
    print(f"Found {len(apk_files)} APK files and {len(ipa_files)} IPA files")
    
    # Analyze a few APK files
    print("\n" + "="*60)
    print("ANALYZING APK FILES")
    print("="*60)
    
    for apk_file in apk_files[:5]:  # Analyze first 5 APK files
        extract_apk_metadata_advanced(apk_file)
    
    # Analyze a few IPA files
    print("\n" + "="*60)
    print("ANALYZING IPA FILES")
    print("="*60)
    
    for ipa_file in ipa_files[:5]:  # Analyze first 5 IPA files
        extract_ipa_metadata_advanced(ipa_file)

if __name__ == "__main__":
    analyze_problematic_files()
