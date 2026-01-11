#!/usr/bin/env python3
"""
Helper script to get Google Keep master token.
"""

import gkeepapi

def main():
    print("=" * 60)
    print("Google Keep Token Generator")
    print("=" * 60)
    print()

    email = input("Enter your Gmail address: ").strip()
    app_password = input("Enter your App Password (16 chars): ").strip()

    # Remove any spaces from app password
    app_password = app_password.replace(" ", "")

    print()
    print("Attempting to authenticate with Google Keep...")

    try:
        keep = gkeepapi.Keep()

        # Try the newer authenticate method
        success = keep.authenticate(email, app_password)

        if success:
            # Get the master token
            master_token = keep.getMasterToken()

            print()
            print("=" * 60)
            print("SUCCESS! Here is your master token:")
            print("=" * 60)
            print()
            print(master_token)
            print()
            print("=" * 60)
            print("Add this to your .env file as:")
            print(f"GOOGLE_KEEP_TOKEN={master_token}")
            print("=" * 60)
        else:
            print("Authentication returned False")

    except gkeepapi.exception.LoginException as e:
        print()
        print(f"Login failed: {e}")
        print()
        print("This is a known issue with gkeepapi and Google's security.")
        print()
        print("Alternative: Try using gpsoauth directly.")
        print("Running alternative method...")
        print()
        try_gpsoauth_method(email, app_password)

    except Exception as e:
        print()
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()


def try_gpsoauth_method(email, app_password):
    """Try using gpsoauth directly to get a master token."""
    try:
        import gpsoauth

        # This requires an android_id - we'll generate one
        import hashlib
        android_id = hashlib.md5(email.encode()).hexdigest()[:16]

        print(f"Using Android ID: {android_id}")
        print()

        # Try to get master token using perform_master_login
        result = gpsoauth.perform_master_login(email, app_password, android_id)

        if 'Token' in result:
            master_token = result['Token']
            print("=" * 60)
            print("SUCCESS with gpsoauth! Here is your master token:")
            print("=" * 60)
            print()
            print(master_token)
            print()
            print("=" * 60)
            print("Add this to your .env file as:")
            print(f"GOOGLE_KEEP_TOKEN={master_token}")
            print("=" * 60)
        else:
            print(f"gpsoauth result: {result}")
            print()
            print("This usually means Google is blocking the login.")
            print()
            print("Unfortunately, Google has made it very difficult to use")
            print("unofficial APIs with personal accounts.")
            print()
            print("Options:")
            print("1. The official Keep API only works with Google Workspace accounts")
            print("2. You may need to temporarily disable 2FA and try again")
            print("3. Or use a different note-taking solution that has a proper API")

    except Exception as e:
        print(f"gpsoauth method also failed: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
