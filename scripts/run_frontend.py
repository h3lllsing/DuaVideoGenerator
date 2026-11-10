"""
Dua Video Generator - Frontend Launcher
Run this file to start the GUI application
"""

import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def main():
    """Main launcher function."""
    print("=" * 50)
    print("  DUA VIDEO GENERATOR")
    print("  Starting Frontend...")
    print("=" * 50)

    try:
        from frontend.wife_app import DuaApp

        print("\nLaunching application...")
        app = DuaApp()
        app.mainloop()

    except ImportError as e:
        print("\nError: Could not import required modules.")
        print(f"Details: {e}")
        print("\nPlease install required packages:")
        print("  pip install customtkinter")

    except Exception as e:
        print(f"\nError starting application: {e}")


if __name__ == "__main__":
    main()
