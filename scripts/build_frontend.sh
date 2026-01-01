#!/bin/bash

# Build frontend script
# This script builds the frontend and prepares it for deployment

echo "Building frontend..."
cd frontend || { echo "Frontend directory not found"; exit 1; }

# Install dependencies if needed
if [ ! -d "node_modules" ]; then
    echo "Installing npm dependencies..."
    npm install
fi

# Build the frontend
npm run build

if [ $? -eq 0 ]; then
    echo "Frontend build completed successfully!"
    echo "The compiled files are in the frontend/dist directory."
    echo "Don't forget to commit the updated dist files if you want to deploy your changes."
else
    echo "Frontend build failed!"
    exit 1
fi