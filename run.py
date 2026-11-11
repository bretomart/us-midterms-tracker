#!/usr/bin/env python3
"""US Midterms Tracker launcher."""
import os
import sys

def main():
    """Start the tracker.

    Change into the directory holding this launcher, print a startup banner,
    then delegate to server.run_server(), which runs the polling daemon and
    HTTP dashboards until interrupted.
    """
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    print("Starting US Midterm Tracker...")
    import server
    server.run_server()

if __name__ == "__main__":
    main()
