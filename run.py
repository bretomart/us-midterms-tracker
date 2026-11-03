#!/usr/bin/env python3
"""US Midterms Tracker launcher."""
import os
import sys

def main():
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    print("Starting US Midterm Tracker...")
    import server
    server.run_server()

if __name__ == "__main__":
    main()
