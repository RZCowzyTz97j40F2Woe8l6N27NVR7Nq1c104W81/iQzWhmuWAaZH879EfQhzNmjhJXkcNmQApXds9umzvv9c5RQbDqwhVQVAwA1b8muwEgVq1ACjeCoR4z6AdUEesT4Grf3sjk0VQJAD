import os, subprocess, csv, zipfile, plistlib, shutil, time, logging, re
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed
from multiprocessing import cpu_count
import tempfile
import threading
import json

# Set up logging
logging.basicConfig(filename="app_analysis.log", level=logging.INFO, 
                   format='%(asctime)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')

def analyze_apk_comprehensive(file_path):
    """Comprehensive APK analysis using multiple methods"""
    result = {
        'file': file_path,
        'methods': {},
        'final_name': '',
        'final_version': '',
        'final_package': '',
        'confidence': 0
    }
    
    try:
        # Method 1: aapt dump badging (current method)
        try:
            aapt_result = subprocess.check_output(
                ["aapt", "dump", "badging", file_path],
                stderr=subprocess.STDOUT,
                text=True,
                timeout=30
            )
            
            label = ""
            package = ""
            version = ""
            
            for line in aapt_result.splitlines():
                if line.startswith("package:"):
                    for part in line.split():
                        if part.startswith("name="):
                            package = part.split("=")[1].strip("'")
                        elif part.startswith("versionName="):
                            version = part.split("=")[1].strip("'")
                elif line.startswith("application-label:"):
                    label = line.split(":", 1)[1].strip("'")
            
            result['methods']['aapt'] = {
                'label': label,
                'package': package,
                'version': version,
                'confidence': 3 if label and package else 1
            }
        except Exception as e:
            result['methods']['aapt'] = {'error': str(e), 'confidence': 0}
        
        # Method 2: aapt dump resources (alternative)
        try:
            resources_result = subprocess.check_output(
                ["aapt", "dump", "resources", file_path],
                stderr=subprocess.STDOUT,
                text=True,
                timeout=30
            )
            
            # Look for app name in resources
            app_name = ""
            for line in resources_result.splitlines():
                if 'app_name' in line.lower() or 'application_name' in line.lower():
                    # Extract string value
                    if 'string' in line:
                        parts = line.split()
                        for part in parts:
                            if 'app_name' in part.lower():
                                app_name = part.split('=')[-1].strip('"\'')
                                break
            
            result['methods']['aapt_resources'] = {
                'app_name': app_name,
                'confidence': 2 if app_name else 0
            }
        except Exception as e:
            result['methods']['aapt_resources'] = {'error': str(e), 'confidence': 0}
        
        # Method 3: Try to extract AndroidManifest.xml
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                # Extract AndroidManifest.xml
                subprocess.run(
                    ["aapt", "dump", "xmltree", file_path, "AndroidManifest.xml"],
                    stdout=open(os.path.join(temp_dir, "manifest.txt"), "w"),
                    stderr=subprocess.DEVNULL,
                    timeout=20
                )
                
                manifest_path = os.path.join(temp_dir, "manifest.txt")
                if os.path.exists(manifest_path):
                    with open(manifest_path, 'r', encoding='utf-8', errors='ignore') as f:
                        manifest_content = f.read()
                    
                    # Look for app name patterns
                    app_name = ""
                    if 'android:label' in manifest_content:
                        # Extract label value
                        import re
                        label_match = re.search(r'android:label="([^"]+)"', manifest_content)
                        if label_match:
                            app_name = label_match.group(1)
                    
                    result['methods']['manifest'] = {
                        'app_name': app_name,
                        'confidence': 2 if app_name else 0
                    }
        except Exception as e:
            result['methods']['manifest'] = {'error': str(e), 'confidence': 0}
        
        # Determine best result
        best_method = None
        best_confidence = 0
        
        for method, data in result['methods'].items():
            if 'confidence' in data and data['confidence'] > best_confidence:
                best_confidence = data['confidence']
                best_method = method
        
        if best_method:
            method_data = result['methods'][best_method]
            result['final_name'] = method_data.get('label', method_data.get('app_name', ''))
            result['final_version'] = method_data.get('version', '')
            result['final_package'] = method_data.get('package', '')
            result['confidence'] = best_confidence
        
        return result
        
    except Exception as e:
        result['error'] = str(e)
        return result

def analyze_ipa_comprehensive(file_path):
    """Comprehensive IPA analysis using multiple methods"""
    result = {
        'file': file_path,
        'methods': {},
        'final_name': '',
        'final_version': '',
        'final_package': '',
        'confidence': 0
    }
    
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            with zipfile.ZipFile(file_path, 'r') as zip_ref:
                # Find all Info.plist files
                info_files = [f for f in zip_ref.namelist() if f.endswith('Info.plist')]
                
                if not info_files:
                    result['error'] = "No Info.plist files found"
                    return result
                
                # Method 1: Find main app Info.plist (current method)
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
                
                try:
                    with open(info_path, 'rb') as fp:
                        info_plist = plistlib.load(fp)
                    
                    # Extract all possible name fields
                    name_fields = {
                        'CFBundleDisplayName': info_plist.get('CFBundleDisplayName', ''),
                        'CFBundleName': info_plist.get('CFBundleName', ''),
                        'CFBundleExecutable': info_plist.get('CFBundleExecutable', ''),
                        'CFBundleDisplayNameLocalized': info_plist.get('CFBundleDisplayNameLocalized', ''),
                        'CFBundleIdentifier': info_plist.get('CFBundleIdentifier', ''),
                        'CFBundleShortVersionString': info_plist.get('CFBundleShortVersionString', ''),
                        'CFBundleVersion': info_plist.get('CFBundleVersion', '')
                    }
                    
                    # Determine best name
                    best_name = ""
                    confidence = 0
                    
                    if name_fields['CFBundleDisplayName']:
                        best_name = name_fields['CFBundleDisplayName']
                        confidence = 4
                    elif name_fields['CFBundleName']:
                        best_name = name_fields['CFBundleName']
                        confidence = 3
                    elif name_fields['CFBundleExecutable']:
                        best_name = name_fields['CFBundleExecutable']
                        confidence = 2
                    elif name_fields['CFBundleDisplayNameLocalized']:
                        best_name = name_fields['CFBundleDisplayNameLocalized']
                        confidence = 3
                    
                    result['methods']['main_plist'] = {
                        'name_fields': name_fields,
                        'best_name': best_name,
                        'confidence': confidence
                    }
                    
                    result['final_name'] = best_name
                    result['final_version'] = name_fields['CFBundleShortVersionString'] or name_fields['CFBundleVersion']
                    result['final_package'] = name_fields['CFBundleIdentifier']
                    result['confidence'] = confidence
                    
                except Exception as e:
                    result['methods']['main_plist'] = {'error': str(e), 'confidence': 0}
                
                # Method 2: Try plutil if available (macOS/Linux)
                try:
                    plutil_result = subprocess.check_output(
                        ["plutil", "-p", info_path],
                        stderr=subprocess.STDOUT,
                        text=True,
                        timeout=10
                    )
                    
                    # Parse plutil output
                    display_name = ""
                    bundle_name = ""
                    
                    for line in plutil_result.splitlines():
                        if 'CFBundleDisplayName' in line:
                            display_name = line.split('"')[-2] if '"' in line else ""
                        elif 'CFBundleName' in line:
                            bundle_name = line.split('"')[-2] if '"' in line else ""
                    
                    result['methods']['plutil'] = {
                        'display_name': display_name,
                        'bundle_name': bundle_name,
                        'confidence': 3 if display_name else 2 if bundle_name else 0
                    }
                    
                except Exception as e:
                    result['methods']['plutil'] = {'error': str(e), 'confidence': 0}
                
                # Method 3: Check all Info.plist files for better data
                for info_file in info_files[:5]:  # Check first 5 plist files
                    if info_file != main_info_file:
                        try:
                            zip_ref.extract(info_file, temp_dir)
                            alt_info_path = os.path.join(temp_dir, info_file)
                            
                            with open(alt_info_path, 'rb') as fp:
                                alt_plist = plistlib.load(fp)
                            
                            alt_name = (alt_plist.get('CFBundleDisplayName') or 
                                       alt_plist.get('CFBundleName') or 
                                       alt_plist.get('CFBundleExecutable') or '')
                            
                            if alt_name and len(alt_name) > len(result['final_name']):
                                result['methods'][f'alt_plist_{len(result["methods"])}'] = {
                                    'name': alt_name,
                                    'file': info_file,
                                    'confidence': 2
                                }
                                
                                if result['confidence'] < 2:
                                    result['final_name'] = alt_name
                                    result['confidence'] = 2
                                    
                        except Exception:
                            continue
        
        return result
        
    except Exception as e:
        result['error'] = str(e)
        return result

def analyze_file(file_path):
    """Analyze a single file using comprehensive methods"""
    file_size_mb = round(os.path.getsize(file_path) / (1024 * 1024), 2)
    
    if file_path.endswith('.apk'):
        result = analyze_apk_comprehensive(file_path)
    elif file_path.endswith('.ipa'):
        result = analyze_ipa_comprehensive(file_path)
    else:
        return None
    
    result['size_mb'] = file_size_mb
    return result

def main():
    start_time = time.time()
    
    # Get all APK and IPA files
    files_to_process = []
    for f in os.listdir("."):
        if f.endswith(".apk") or f.endswith(".ipa"):
            files_to_process.append(f)
    
    print(f"Found {len(files_to_process)} files to analyze")
    print(f"Using {cpu_count()} CPU cores for parallel analysis")
    
    # Analyze files in parallel
    analysis_results = []
    
    with ProcessPoolExecutor(max_workers=cpu_count()) as executor:
        future_to_file = {executor.submit(analyze_file, f): f for f in files_to_process}
        
        for future in as_completed(future_to_file):
            file = future_to_file[future]
            try:
                result = future.result()
                if result:
                    analysis_results.append(result)
                    print(f"Analyzed {file}: {result['final_name']} v{result['final_version']} (confidence: {result['confidence']})")
            except Exception as e:
                logging.error(f"Failed to analyze {file}: {str(e)}")
    
    # Write detailed analysis to JSON
    with open("app_analysis_detailed.json", "w", encoding="utf-8") as f:
        json.dump(analysis_results, f, indent=2, ensure_ascii=False)
    
    # Write summary CSV
    with open("app_analysis_summary.csv", "w", newline="", encoding="utf-8") as out:
        w = csv.writer(out, delimiter='|')
        w.writerow(["file", "name", "version", "package", "confidence", "size_mb", "methods_used"])
        
        for result in analysis_results:
            methods_used = ", ".join(result['methods'].keys())
            w.writerow([
                result['file'],
                result['final_name'],
                result['final_version'],
                result['final_package'],
                result['confidence'],
                result['size_mb'],
                methods_used
            ])
    
    # Statistics
    total_files = len(analysis_results)
    high_confidence = len([r for r in analysis_results if r['confidence'] >= 3])
    medium_confidence = len([r for r in analysis_results if 1 <= r['confidence'] < 3])
    low_confidence = len([r for r in analysis_results if r['confidence'] == 0])
    
    end_time = time.time()
    processing_time = round(end_time - start_time, 2)
    
    print(f"\nAnalysis completed in {processing_time} seconds")
    print(f"Total files analyzed: {total_files}")
    print(f"High confidence (3+): {high_confidence}")
    print(f"Medium confidence (1-2): {medium_confidence}")
    print(f"Low confidence (0): {low_confidence}")
    
    # Show files with low confidence
    low_conf_files = [r for r in analysis_results if r['confidence'] == 0]
    if low_conf_files:
        print(f"\nFiles with low confidence ({len(low_conf_files)}):")
        for result in low_conf_files[:10]:  # Show first 10
            print(f"  - {result['file']}")
        if len(low_conf_files) > 10:
            print(f"  ... and {len(low_conf_files) - 10} more")

if __name__ == "__main__":
    main()
