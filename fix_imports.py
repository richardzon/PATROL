#!/usr/bin/env python3

import os
import re

# Path to the miner.py file
miner_path = os.path.join('src', 'patrol', 'mining', 'miner.py')

# Read the file
with open(miner_path, 'r') as f:
    content = f.read()

# Fix the imports
fixed_content = re.sub(
    r'from patrol\.', 
    'from src.patrol.', 
    content
)

# Write the fixed content back
with open(miner_path, 'w') as f:
    f.write(fixed_content)

print(f"Fixed imports in {miner_path}")

# Now fix other files that might be imported
for root, dirs, files in os.walk('src'):
    for file in files:
        if file.endswith('.py') and file != 'miner.py':
            file_path = os.path.join(root, file)
            
            # Read the file
            with open(file_path, 'r') as f:
                content = f.read()
            
            # Fix the imports
            fixed_content = re.sub(
                r'from patrol\.', 
                'from src.patrol.', 
                content
            )
            
            # Write the fixed content back
            with open(file_path, 'w') as f:
                f.write(fixed_content)
            
            print(f"Fixed imports in {file_path}")

print("All imports fixed!")
print("Now you can run the miner with:")
print("./start_optimized_miner.sh")
