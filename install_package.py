#!/usr/bin/env python3

import os
import sys
import subprocess
import site

# Get the current directory
current_dir = os.path.dirname(os.path.abspath(__file__))

# Create a .pth file in the site-packages directory
site_packages_dirs = site.getsitepackages()
user_site = site.getusersitepackages()

all_site_dirs = site_packages_dirs + [user_site]

success = False

for site_dir in all_site_dirs:
    try:
        # Create a .pth file that points to the current directory
        pth_file = os.path.join(site_dir, 'patrol_subnet.pth')
        with open(pth_file, 'w') as f:
            f.write(current_dir)
        print(f"Created {pth_file} pointing to {current_dir}")
        success = True
    except Exception as e:
        print(f"Could not create .pth file in {site_dir}: {e}")

if not success:
    print("Could not create .pth file in any site-packages directory.")
    print("Trying to install using pip...")
    
    try:
        # Try to install using pip
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', '-e', current_dir])
        print("Successfully installed package using pip.")
        success = True
    except Exception as e:
        print(f"Could not install using pip: {e}")

if not success:
    print("\nManual installation instructions:")
    print("1. Add the following line to your ~/.bashrc or ~/.profile:")
    print(f"   export PYTHONPATH=$PYTHONPATH:{current_dir}")
    print("2. Run: source ~/.bashrc")
    print("3. Restart your miner")
else:
    print("\nPackage installed successfully!")
    print("You can now run the miner with:")
    print("./start_optimized_miner.sh")
