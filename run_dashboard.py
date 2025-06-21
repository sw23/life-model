#!/usr/bin/env python3
"""
Run the Life Model Financial Simulation Dashboard

This script starts the Solara server and displays the interactive dashboard
for the life_model financial simulation.

Usage:
    python run_dashboard.py

Then open your browser to http://localhost:8765
"""

import sys
import os

# Add the src directory to Python path so we can import life_model
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

try:
    from dashboard import create_dashboard
    import solara
    
    # Create the dashboard
    dashboard = create_dashboard()
    
    # Define the main page function that Solara will use
    @solara.component
    def Page():
        return dashboard
    
    # This will be automatically picked up by Solara when running with `solara run`
    
    if __name__ == "__main__":
        print("Starting Life Model Financial Simulation Dashboard...")
        print("Run with: solara run run_dashboard.py")
        print("Then open your browser to: http://localhost:8765")
        
        # For development, you can also run with uvicorn directly:
        # uvicorn run_dashboard:app --host 127.0.0.1 --port 8765
        
except ImportError as e:
    print(f"Error importing dependencies: {e}")
    print("Make sure you have installed all required packages:")
    print("pip install mesa solara altair networkx")
    sys.exit(1)
except Exception as e:
    print(f"Error creating dashboard: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)