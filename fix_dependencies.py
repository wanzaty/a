#!/usr/bin/env python3
"""
Script untuk memperbaiki dependency conflicts
"""
import subprocess
import sys

def main():
    print("🔧 Memperbaiki dependency conflicts...")
    
    # Daftar packages yang perlu diupgrade
    packages_to_upgrade = [
        "httpx>=0.28.1",
        "httpcore>=1.0.0", 
        "h11>=0.14.0",
        "h2>=4.0.0",
        "idna>=3.0",
        "pydantic>=2.11.5"
    ]
    
    try:
        # Upgrade packages yang konflik
        print("📦 Mengupgrade packages...")
        for package in packages_to_upgrade:
            print(f"   Upgrading {package}...")
            subprocess.check_call([sys.executable, "-m", "pip", "install", "--upgrade", package])
        
        # Reinstall selenium-wire
        print("🔄 Reinstalling selenium-wire...")
        subprocess.check_call([sys.executable, "-m", "pip", "uninstall", "-y", "selenium-wire"])
        subprocess.check_call([sys.executable, "-m", "pip", "install", "selenium-wire>=5.1.0"])
        
        # Verify installation
        print("✅ Verifying installation...")
        try:
            from seleniumwire import webdriver
            print("✅ selenium-wire berhasil diinstall!")
        except ImportError as e:
            print(f"❌ selenium-wire masih bermasalah: {e}")
            return False
            
        print("🎉 Semua dependencies berhasil diperbaiki!")
        print("💡 Silakan jalankan script utama sekarang.")
        return True
        
    except subprocess.CalledProcessError as e:
        print(f"❌ Error saat menginstall packages: {e}")
        return False
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        return False

if __name__ == "__main__":
    main()