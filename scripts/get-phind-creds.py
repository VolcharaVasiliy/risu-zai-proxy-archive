#!/usr/bin/env python
"""
Extract Phind cookies from dedicated Edge profile.
Usage: python scripts/get-phind-creds.py [--profile-root PATH] [--output PATH]
"""
import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

# Add pydeps to path for cryptography
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "pydeps"))

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.backends import default_backend
except ImportError:
    print("Error: cryptography module not found")
    print("Install with: pip install cryptography")
    sys.exit(1)


def get_encryption_key_windows(profile_root):
    """Get the encryption key from Edge Local State file on Windows."""
    # Try profile_root/Local State first, then parent/Local State
    local_state_path = Path(profile_root) / "Local State"
    if not local_state_path.exists():
        local_state_path = Path(profile_root).parent / "Local State"
    
    if not local_state_path.exists():
        raise RuntimeError(f"Local State file not found: {local_state_path}")
    
    with open(local_state_path, "r", encoding="utf-8") as f:
        local_state = json.load(f)
    
    encrypted_key = local_state.get("os_crypt", {}).get("encrypted_key")
    if not encrypted_key:
        raise RuntimeError("Encrypted key not found in Local State")
    
    import base64
    encrypted_key_bytes = base64.b64decode(encrypted_key)
    
    # Remove DPAPI prefix
    if encrypted_key_bytes[:5] != b"DPAPI":
        raise RuntimeError("Invalid encrypted key format")
    
    encrypted_key_bytes = encrypted_key_bytes[5:]
    
    # Decrypt using Windows DPAPI
    import win32crypt
    key = win32crypt.CryptUnprotectData(encrypted_key_bytes, None, None, None, 0)[1]
    return key


def decrypt_cookie_value(encrypted_value, key):
    """Decrypt Edge cookie value."""
    if not encrypted_value:
        return ""
    
    # Check for v10 or v11 prefix
    if encrypted_value[:3] == b"v10" or encrypted_value[:3] == b"v11":
        # Remove version prefix
        encrypted_value = encrypted_value[3:]
        
        # Extract nonce and ciphertext
        nonce = encrypted_value[:12]
        ciphertext = encrypted_value[12:]
        
        # Decrypt using AES-GCM
        cipher = AESGCM(key)
        try:
            decrypted = cipher.decrypt(nonce, ciphertext, None)
            return decrypted.decode("utf-8")
        except Exception as e:
            print(f"Warning: Failed to decrypt cookie: {e}")
            return ""
    
    # Fallback for older format
    return encrypted_value.decode("utf-8", errors="ignore")


def extract_phind_cookies(profile_root):
    """Extract Phind cookies from Edge profile."""
    cookies_db_path = Path(profile_root) / "Default" / "Network" / "Cookies"
    
    if not cookies_db_path.exists():
        # Try alternative path
        cookies_db_path = Path(profile_root) / "Default" / "Cookies"
    
    if not cookies_db_path.exists():
        raise RuntimeError(f"Cookies database not found: {cookies_db_path}")
    
    # Copy database to temp location (Edge locks the file)
    import tempfile
    import shutil
    temp_db = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
    temp_db.close()
    shutil.copy2(cookies_db_path, temp_db.name)
    
    try:
        # Get encryption key
        key = get_encryption_key_windows(profile_root)
        
        # Connect to cookies database
        conn = sqlite3.connect(temp_db.name)
        cursor = conn.cursor()
        
        # Query Phind cookies
        cursor.execute("""
            SELECT name, encrypted_value, host_key, path, expires_utc, is_secure, is_httponly
            FROM cookies
            WHERE host_key LIKE '%phind.com%'
            ORDER BY creation_utc DESC
        """)
        
        cookies = []
        for row in cursor.fetchall():
            name, encrypted_value, host_key, path, expires_utc, is_secure, is_httponly = row
            
            # Decrypt cookie value
            value = decrypt_cookie_value(encrypted_value, key)
            
            if value:
                cookies.append({
                    "name": name,
                    "value": value,
                    "domain": host_key,
                    "path": path,
                    "expires": expires_utc,
                    "secure": bool(is_secure),
                    "httpOnly": bool(is_httponly)
                })
        
        conn.close()
        return cookies
    
    finally:
        # Clean up temp file
        try:
            os.unlink(temp_db.name)
        except Exception:
            pass


def build_cookie_header(cookies):
    """Build Cookie header string from cookie list."""
    cookie_pairs = []
    for cookie in cookies:
        cookie_pairs.append(f"{cookie['name']}={cookie['value']}")
    return "; ".join(cookie_pairs)


def main():
    parser = argparse.ArgumentParser(description="Extract Phind cookies from Edge profile")
    parser.add_argument(
        "--profile-root",
        default=None,
        help="Path to Edge profile directory (default: auth/phind-edge-profile)"
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output JSON file path (default: auth/phind-creds.json)"
    )
    args = parser.parse_args()
    
    # Determine paths
    script_dir = Path(__file__).parent
    project_root = script_dir.parent
    
    if args.profile_root:
        profile_root = Path(args.profile_root)
    else:
        profile_root = project_root / "auth" / "phind-edge-profile"
    
    if args.output:
        output_path = Path(args.output)
    else:
        output_path = project_root / "auth" / "phind-creds.json"
    
    print(f"Extracting Phind cookies from: {profile_root}")
    print()
    
    try:
        cookies = extract_phind_cookies(profile_root)
        
        if not cookies:
            print("Warning: No Phind cookies found!")
            print("Make sure you:")
            print("  1. Ran scripts/launch-phind-auth.ps1")
            print("  2. Logged in to phind.com")
            print("  3. Closed the browser")
            sys.exit(1)
        
        print(f"Found {len(cookies)} Phind cookies:")
        for cookie in cookies:
            print(f"  - {cookie['name']} (domain: {cookie['domain']})")
        print()
        
        # Build cookie header
        cookie_header = build_cookie_header(cookies)
        
        # Save to JSON
        output_data = {
            "cookie": cookie_header,
            "cookies": cookies
        }
        
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(output_data, f, indent=2)
        
        print(f"✓ Credentials saved to: {output_path}")
        print()
        print("Cookie header preview:")
        print(f"  {cookie_header[:100]}...")
        print()
        print("You can now use Phind provider with:")
        print(f"  $env:PHIND_COOKIE = '{cookie_header}'")
        print("  python py/server.py")
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
