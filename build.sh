#!/usr/bin/env bash
set -e

# Install Python dependencies
pip install -r requirements.txt

# Install Node.js dependencies for Remotion carousel renderer
if command -v node &> /dev/null; then
    echo "Node.js found: $(node --version)"
    cd remotion && npm install && npx remotion browser ensure && cd ..
    echo "Remotion installed successfully"
else
    echo "WARNING: Node.js not found — carousel PNG rendering will be unavailable"
    echo "To enable, add Node.js to your Render service (use Docker or nixpacks)"
fi
