import telebot
from telebot import types
import threading
import time
import random
import undetected_chromedriver as uc
# Import selenium-wire untuk proxy
try:
    from seleniumwire import webdriver as webdriver_wire
except ImportError:
    print("[ERROR] Modul 'selenium-wire' tidak terinstall. Silakan jalankan: pip install selenium-wire")
    webdriver_wire = None

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver import ActionChains
from selenium.common.exceptions import TimeoutException, WebDriverException, ElementClickInterceptedException, StaleElementReferenceException
import requests
import base64
from imapclient import IMAPClient
from imapclient.exceptions import LoginError
import pyzmail
import re
from faker import Faker
from faker.config import AVAILABLE_LOCALES
import os
import json

# --- START LOGGING CONFIGURATION ---
import logging

# Set the root logger level to CRITICAL to suppress almost all messages
# This is a very aggressive suppression. Use with caution as it might hide
# useful debug information if you encounter unexpected issues.
logging.basicConfig(level=logging.CRITICAL)

# Optionally, you can set specific loggers to a higher level if you want to see
# errors from specific Python modules but still suppress most Chrome output.
# For example, to see ERRORs from TeleBot:
logging.getLogger('TeleBot').setLevel(logging.ERROR)
# --- END LOGGING CONFIGURATION ---


# --- Gemini API ---
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold

# --- Optional: Import pycountry for better locale detection ---
try:
    import pycountry
except ImportError:
    pycountry = None
    print("[Info] Modul 'pycountry' tidak terinstall. Konversi nama negara ke kode mungkin kurang akurat untuk beberapa kasus.")

# --- Import Pillow untuk Watermark ---
try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("[ERROR] Modul 'Pillow' tidak terinstall. Fitur watermark tidak akan berfungsi. Jalankan: pip install Pillow")
    Image = None


# =============== TELEGRAM BOT TOKEN & API KEYS =================
BOT_TOKEN = '7270354626:AAGstKOdIAAk8iKdmF2Rc_ycaEi8mb80UKU' # GANTI DENGAN TOKEN BOT ANDA
GEMINI_API_KEY = 'AIzaSyBFAZsejvYAsgQXz08Sb-uxZVV6o6RriWU' # GANTI DENGAN API KEY GEMINI ANDA

# Konfigurasi Gemini API
genai.configure(api_key=GEMINI_API_KEY)
# Pilih model yang sesuai, 'gemini-pro' adalah pilihan umum untuk teks
gemini_model = genai.GenerativeModel(
    'gemini-2.0-flash',
    safety_settings={
        HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
    }
)

# Set the timeout for TeleBot API calls. This is for Telegram's server response.
# If you are using pyTelegramBotAPI < 4.0.0, use telebot.apihelper.RETRY_TIMEOUT = 90
# If you are using pyTelegramBotAPI >= 4.0.0, use the timeout argument in the constructor
try:
    # Attempt to use the newer constructor argument
    bot = telebot.TeleBot(BOT_TOKEN, timeout=90)
except TypeError:
    # Fallback for older versions
    telebot.apihelper.RETRY_TIMEOUT = 90
    bot = telebot.TeleBot(BOT_TOKEN)

# --- Variabel Global untuk Mengontrol Proses Signup ---
process_events = {} # Dictionary to store a threading.Event for each user
manual_input_data = {} # Dictionary to store manual input from user

# =============== GLOBAL CONSTANTS (Pesan Deteksi Bot) =================
BOT_DETECTION_MESSAGE = (
    "‼️ *DETEKSI BOT / VCC BERMASALAH!* ‼️\n\n"
    "Proses dihentikan. Ini seringkali berarti:\n"
    "1. VCC yang digunakan terdeteksi mencurigakan oleh AWS.\n"
    "2. IP/profil browser Anda terdeteksi sebagai non-manusiawi.\n\n"
    "*Solusi:* Mohon *ganti VCC Anda* dengan yang baru dan coba gunakan *negara yang berbeda* (jika memungkinkan) pada pengaturan bot. Jika masih gagal, pertimbangkan untuk mengubah IP Anda."
)

# Global variable to store SMSHub country and operator data
SMSHUB_DATA = {}
COUNTRY_OPERATORS_FILE = 'country-and-operators.txt'

# =============== UTILS (Fungsi-fungsi umum yang dipanggil di berbagai tempat) =================

def escape_markdown_v1(text):
    """Escape characters for Telegram's legacy Markdown parse mode."""
    escape_chars = '_*`['
    return re.sub(r'([%s])' % re.escape(escape_chars), r'\\\1', text)

def get_proxy_info(proxy_string):
    """Mendeteksi negara dari IP proxy menggunakan ip-api.com."""
    if not proxy_string:
        return None
    try:
        # Extract IP from proxy string
        parts = proxy_string.split(':')
        proxy_ip = parts[0]
        
        # Call API to get geolocation info
        response = requests.get(f'http://ip-api.com/json/{proxy_ip}', timeout=10)
        response.raise_for_status()
        data = response.json()
        
        if data.get('status') == 'success':
            return {
                'country': data.get('country', 'Unknown'),
                'countryCode': data.get('countryCode', 'N/A'),
                'city': data.get('city', 'Unknown'),
                'isp': data.get('isp', 'Unknown')
            }
        else:
            print(f"[Proxy Check] Gagal mendapatkan info untuk IP {proxy_ip}: {data.get('message')}")
            return None
    except Exception as e:
        print(f"[Proxy Check] Error saat memeriksa proxy: {e}")
        return None


def get_user_dir(message):
    """Mendapatkan atau membuat direktori untuk pengguna."""
    uname = message.from_user.username
    if uname:
        folder = f"user/{uname}"
    else:
        folder = f"user/id_{message.from_user.id}"
    os.makedirs(folder, exist_ok=True)
    return folder

def save_user_settings(message, data):
    """Menyimpan pengaturan pengguna ke file JSON."""
    user_dir = get_user_dir(message)
    with open(os.path.join(user_dir, "settings.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)

def load_user_settings(message):
    """Memuat pengaturan pengguna dari file JSON."""
    user_dir = get_user_dir(message)
    path = os.path.join(user_dir, "settings.json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            try:
                settings = json.load(f)
                # Set default email_mode if not present
                if 'email_mode' not in settings:
                    settings['email_mode'] = 'Random'
                return settings
            except json.JSONDecodeError:
                return {'email_mode': 'Random'} # Default
    return {'email_mode': 'Random'} # Default for new users


def send_log(chat_id, text, parse_mode='Markdown', is_error=False, photo_path=None):
    """
    Mengirim log ke konsol dan ke chat Telegram.
    Jika is_error=True, pesan ke Telegram akan disederhanakan.
    Includes retry mechanism for Telegram API calls.
    """
    # Print to console without escaping
    print(text) 

    telegram_text = text # Defaultnya, kirim teks asli

    if is_error:
        # If there's a specific error message already defined
        if "API Key Salah" in text:
            telegram_text = "❌ *API Key Salah! Proses dihentikan.* ❌\n\n" \
                            "Mohon periksa kembali API Key Anti-Captcha atau SMSHub Anda."
        elif "Gagal memverifikasi OTP email" in text:
            telegram_text = "❌ *Verifikasi OTP Email Gagal! Proses dihentikan.* ❌\n\n" \
                            "Pastikan email Gmail Anda benar dan App Password sudah diatur dengan benar, atau OTP manual yang dimasukkan salah."
        elif "Gagal verifikasi telepon" in text:
            telegram_text = "❌ *Verifikasi Telepon Gagal! Proses dihentikan.* ❌\n\n" \
                            "Mohon cek kembali pengaturan SMSHub atau coba negara/operator lain."
        elif "VCC yang digunakan terdeteksi mencurigakan" in text or "DETEKSI BOT / VCC BERMASALAH!" in text:
             # Use the standard BOT_DETECTION_MESSAGE for all bot detection cases
             telegram_text = BOT_DETECTION_MESSAGE 
        elif "Nomor Kartu Kredit tidak valid" in text:
            telegram_text = "❌ *Nomor Kartu Kredit Tidak Valid! Proses dihentikan.* ❌\n\n" \
                            "Mohon periksa kembali nomor kartu kredit Anda."
        elif "Root Password minimal 8 karakter" in text:
            telegram_text = "❌ *Root Password Tidak Sesuai! Proses dihentikan.* ❌\n\n" \
                            "Root Password minimal 8 karakter."
        elif "Nomor telepon tidak valid" in text:
            telegram_text = "❌ *Nomor Telepon Kontak Tidak Valid! Proses dihentikan.* ❌\n\n" \
                            "Mohon cek kembali pengaturan negara atau coba nomor lain."
        elif "Pengaturan SMSHub" in text and "belum lengkap" in text:
            telegram_text = "❌ *Pengaturan SMSHub Belum Lengkap! Proses dihentikan.* ❌\n\n" \
                            "Mohon lengkapi semua pengaturan SMSHub (API Key, Negara, Operator, Harga Maksimal)."
        elif "Gagal mendapatkan informasi dari Wanbot" in text:
            telegram_text = "⚠️ *Masalah Wanbot API!* ⚠️\n\n" \
                            "Gagal mendapatkan data alamat/telepon dari Wanbot. " \
                            "Pastikan API Key Anda valid dan berfungsi. " \
                            "Bot akan menggunakan data Faker sebagai fallback."
        else: # For non-specific errors, use a default message
            telegram_text = "❌ *Terjadi Error! Proses dihentikan.* ❌\n\n" \
                            "Silakan cek log konsol bot untuk detail teknis, " \
                            "atau ulangi proses jika ini adalah error sementara."
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            if photo_path and os.path.exists(photo_path):
                bot.send_photo(chat_id, open(photo_path, "rb"), caption=telegram_text, parse_mode=parse_mode)
            else:
                bot.send_message(chat_id, telegram_text, parse_mode=parse_mode)
            return # Success, exit function
        except requests.exceptions.ReadTimeout as e:
            print(f"[Telegram Send] ReadTimeout during attempt {attempt + 1}/{max_retries}: {e}. Retrying...")
            time.sleep(5 * (attempt + 1)) # Exponential backoff
        except telebot.apihelper.ApiException as e:
            # If the error is about parsing entities, it's a Markdown issue. Try sending as plain text.
            if "can't parse entities" in str(e):
                print(f"[Telegram Send] Markdown Parse Error: {e}. Retrying as plain text...")
                try:
                    if photo_path and os.path.exists(photo_path):
                        bot.send_photo(chat_id, open(photo_path, "rb"), caption=text)
                    else:
                        bot.send_message(chat_id, text)
                    return
                except Exception as e_plain:
                    print(f"[Telegram Send] Failed to send as plain text after Markdown error: {e_plain}")
            else:
                print(f"[Telegram Send] API Error during attempt {attempt + 1}/{max_retries}: {e}. Retrying...")
                time.sleep(5 * (attempt + 1))
        except Exception as e:
            print(f"[Telegram Send] Unexpected error during attempt {attempt + 1}/{max_retries}: {e}. Retrying...")
            time.sleep(5 * (attempt + 1))
    
    # Fallback if all retries fail
    print(f"[Telegram Send] Failed to send message to chat_id {chat_id} after {max_retries} attempts.")
    print(f"Original text: {text}")
    print(f"Telegram text: {telegram_text}")


def random_sleep(a=1.0, b=3.0):
    """Menjalankan time.sleep dengan durasi acak."""
    time.sleep(random.uniform(a, b))

def input_with_delay(element, text):
    """Mengisi input field dengan delay per karakter."""
    element.clear()
    for char in text:
        element.send_keys(char)
        time.sleep(random.uniform(0.05, 0.15))

# ENHANCED CLICK FUNCTION
def click_with_mouse(driver, element):
    """Melakukan klik mouse dengan sedikit delay dan offset acak untuk simulasi manusiawi."""
    actions = ActionChains(driver)
    
    # Get element dimensions and location
    size = element.size
    # location = element.location # Not strictly needed for offset from element center

    # Generate random offset within a reasonable percentage of the element's size
    # This prevents clicking always at the exact center
    offset_x = random.uniform(-size['width'] * 0.3, size['width'] * 0.3)
    offset_y = random.uniform(-size['height'] * 0.3, size['height'] * 0.3)
    
    actions.move_to_element_with_offset(element, offset_x, offset_y) \
           .pause(random.uniform(0.2, 0.6)) \
           .click() \
           .perform()
    random_sleep(0.4, 1.2) # Slightly reduced post-click sleep

def click_double_with_mouse(driver, element):
    """Melakukan klik ganda mouse dengan sedikit delay dan offset acak untuk simulasi manusiawi."""
    actions = ActionChains(driver)
    
    size = element.size
    offset_x = random.uniform(-size['width'] * 0.3, size['width'] * 0.3)
    offset_y = random.uniform(-size['height'] * 0.3, size['height'] * 0.3)
    
    actions.move_to_element_with_offset(element, offset_x, offset_y) \
           .pause(random.uniform(0.2, 0.5)) \
           .click() \
           .pause(random.uniform(0.2, 0.5)) \
           .click() \
           .perform()
    random_sleep(0.4, 1.2)

def save_screenshot(driver, user_dir, step_name):
    """Menyimpan screenshot untuk debugging dengan watermark."""
    if Image is None:
        print("[Warning] Pillow tidak terinstall, screenshot tidak akan diberi watermark.")
        filename = os.path.join(user_dir, "screenshots", f"{int(time.time())}_{step_name}.png")
        try:
            driver.save_screenshot(filename)
            return filename
        except Exception as e:
            print(f"Gagal menyimpan screenshot: {e}")
            return None

    screenshot_dir = os.path.join(user_dir, "screenshots")
    os.makedirs(screenshot_dir, exist_ok=True)
    filename = os.path.join(screenshot_dir, f"{int(time.time())}_{step_name}.png")
    
    try:
        # Simpan screenshot ke file sementara
        temp_filename = os.path.join(screenshot_dir, "temp_screenshot.png")
        driver.save_screenshot(temp_filename)

        # Buka gambar dan tambahkan watermark
        with Image.open(temp_filename) as img:
            draw = ImageDraw.Draw(img)
            width, height = img.size
            
            # Tentukan font size berdasarkan lebar gambar
            font_size = int(width / 12)
            
            # Coba muat font Arial, jika tidak ada, gunakan font default
            try:
                font = ImageFont.truetype("arial.ttf", font_size)
            except IOError:
                print("[Warning] Font Arial tidak ditemukan, menggunakan font default.")
                font = ImageFont.load_default()

            watermark_text = "WANZATY"
            
            # Hitung bounding box untuk teks
            text_bbox = draw.textbbox((0, 0), watermark_text, font=font)
            text_width = text_bbox[2] - text_bbox[0]
            text_height = text_bbox[3] - text_bbox[1]
            
            # Posisi watermark di tengah
            position = ((width - text_width) / 2, (height - text_height) / 2)
            
            # Warna biru dengan transparansi (RGBA)
            text_color = (0, 0, 255, 128) # Biru, 50% opacity
            
            # Gambar watermark
            draw.text(position, watermark_text, font=font, fill=text_color)
            
            # Simpan gambar dengan watermark
            img.save(filename)

        # Hapus file sementara
        if os.path.exists(temp_filename):
            os.remove(temp_filename)
            
        return filename
    except Exception as e:
        print(f"Gagal menyimpan screenshot dengan watermark: {e}")
        return None

def get_faker_locale(country_name_input: str) -> str:
    """Mencoba menentukan locale Faker berdasarkan nama negara."""
    country_name = country_name_input.lower()
    default_locale = "en-US"

    if '_' in country_name and country_name.replace("_", "-") in AVAILABLE_LOCALES:
        return country_name.replace("_", "-")
    if '-' in country_name and country_name in AVAILABLE_LOCALES:
        return country_name

    if pycountry:
        try:
            country_data = None
            for lookup_method in [pycountry.countries.get, pycountry.countries.search_fuzzy]:
                try:
                    if lookup_method == pycountry.countries.get:
                        country_data = lookup_method(name=country_name)
                        if not country_data: country_data = lookup_method(common_name=country_name)
                        if not country_data: country_data = lookup_method(official_name=country_name)
                        if not country_data: country_data = lookup_method(alpha_2=country_name.upper())
                    elif lookup_method == pycountry.countries.search_fuzzy:
                        results = lookup_method(country_name)
                        if results: country_data = results[0]
                except Exception:
                    # Continue to next lookup_method if there's an error
                    continue
                
                if country_data: # Check outside the inner try-except
                    break # Break the for loop if country_data is found

            if country_data:
                alpha_2 = country_data.alpha_2.lower()
                common_langs_map = {
                    'us': 'en', 'gb': 'en', 'ca': 'en', 'au': 'en', 'nz': 'en',
                    'id': 'id', 'de': 'de', 'fr': 'fr', 'es': 'es', 'it': 'it',
                    'jp': 'ja', 'kr': 'ko', 'cn': 'zh', 'ru': 'ru', 'br': 'pt',
                    'in': 'en',
                }
                lang_prefix = common_langs_map.get(alpha_2, alpha_2)

                potential_locale = f"{lang_prefix}-{alpha_2.upper()}"
                if potential_locale in AVAILABLE_LOCALES:
                    return potential_locale

                en_locale = f"en-{alpha_2.upper()}"
                if en_locale in AVAILABLE_LOCALES:
                    return en_locale
        except Exception as e_pyc:
            print(f"[Debug] pycountry error for '{country_name}': {e_pyc}")
            pass

    specific_locale_map = {
        "usa": "en-US", "united states": "en-US", "united states of america": "en-US",
        "uk": "en-GB", "united kingdom": "en-GB", "great britain": "en-GB",
        "uae": "ar-AE", "united arab Emirates": "ar-AE",
        "vietnam": "vi-VN",
        "new Zealand": "en-NZ"
    }
    if country_name in specific_locale_map:
        if specific_locale_map[country_name] in AVAILABLE_LOCALES:
            return specific_locale_map[country_name]

    first_word = country_name.split(' ')[0]
    if len(first_word) >= 2:
        lang_guess = first_word[:2]
        region_guess_from_first_word = first_word[:2].upper()
        region_guess_from_country_name = country_name[:2].upper() if len(country_name) >=2 else region_guess_from_first_word

        for region_try in {region_guess_from_first_word, region_guess_from_country_name}:
            potential_locale_direct = f"{lang_guess}-{region_try}"
            if potential_locale_direct in AVAILABLE_LOCALES:
                return potential_locale_direct
            potential_locale_en = f"en-{region_try}"
            if potential_locale_en in AVAILABLE_LOCALES:
                return potential_locale_en

    for locale_code in AVAILABLE_LOCALES:
        if country_name == locale_code.lower() or country_name == locale_code.lower().replace("-","_"):
             return locale_code
        if '-' in locale_code:
            try:
                _, country_part = locale_code.split('-',1)
                if country_name == country_part.lower():
                    return locale_code
            except ValueError:
                continue

    print(f"[Warning] Tidak dapat menentukan locale Faker secara spesifik untuk '{country_name_input}'. Menggunakan default: {default_locale}")
    return default_locale

def get_wanbot_address_and_phone_info(country_name: str, chat_id=None):
    """
    Menggunakan API untuk menghasilkan informasi alamat dan format nomor telepon
    berdasarkan nama negara.
    """
    log_prefix = "[Wanbot]" if chat_id else "[Wanbot-Internal]"
    if chat_id: send_log(chat_id, f"{log_prefix} Meminta informasi alamat dan telepon untuk '{country_name}'...")
    
    # Menambahkan elemen acak ke prompt
    random_phrase = random.choice([
        "Provide a realistic street address for a residential property.",
        "Generate a plausible address, focusing on a typical suburban street.",
        "Give me a street address for a fictional person.",
        "Construct a valid street address, city, and postal code.",
        "I need a complete street address and phone number example."
    ])
    
    # Perkuat prompt Gemini untuk memastikan negara yang benar digunakan
    prompt = (
        f"{random_phrase} in {country_name}. " # Ulangi nama negara
        f"Also include a state/province if applicable for {country_name}, or just repeat the city name if not. "
        f"And a plausible full local phone number example (including country code prefix like +XX) "
        f"for a location in {country_name}. " # Ulangi nama negara
        f"Ensure all generated data is consistent with {country_name}. " # Penekanan tambahan
        f"Provide the output in a structured JSON format with the following keys: "
        f"`street_address`, `city`, `state_province`, `postal_code`, `phone_number_example`. "
        f"If a state/province is not applicable for the country, use the city name for `state_province`. "
        f"Do not include any other text or greetings, only the JSON object."
    )

    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = gemini_model.generate_content(prompt)
            raw_text = response.text.strip()
            
            json_match = re.search(r"\{.*\}", raw_text, re.DOTALL)
            if json_match:
                json_str = json_match.group(0)
                data = json.loads(json_str)
                # Escape JSON string before passing to send_log
                if chat_id: send_log(chat_id, f"{log_prefix} Data diterima: `{json.dumps(data)}`") 
                return {
                    'street_address': data.get('street_address', ''),
                    'city': data.get('city', ''),
                    'state_province': data.get('state_province', ''),
                    'postal_code': data.get('postal_code', ''),
                    'phone_number_example': data.get('phone_number_example', '')
                }
            else:
                if chat_id: send_log(chat_id, f"{log_prefix} Gagal mengekstrak JSON dari respon. Respon mentah: {raw_text}. Percobaan {attempt+1}/{max_retries}.")
        except json.JSONDecodeError as e:
            if chat_id: send_log(chat_id, f"{log_prefix} Respon bukan JSON valid: {e}. Respon mentah: {raw_text}. Percobaan {attempt+1}/{max_retries}.")
        except Exception as e:
            if chat_id: send_log(chat_id, f"{log_prefix} Error saat memanggil API: {e}. Percobaan {attempt+1}/{max_retries}.")
        
        time.sleep(random.uniform(2, 5))

    if chat_id: send_log(chat_id, f"{log_prefix} Gagal mendapatkan informasi dari Wanbot setelah beberapa percobaan.", is_error=True)
    return None

def get_country_phone_code(country_name: str) -> str:
    """
    Mengambil kode telepon internasional untuk negara tertentu.
    Akan mengembalikan string kosong jika tidak ditemukan.
    """
    if pycountry:
        try:
            country_data = None
            for lookup_method in [pycountry.countries.get, pycountry.countries.search_fuzzy]:
                try:
                    if lookup_method == pycountry.countries.get:
                        country_data = lookup_method(name=country_name)
                        if not country_data: country_data = lookup_method(common_name=country_name)
                        if not country_data: country_data = lookup_method(official_name=country_name)
                        if not country_data: country_data = lookup_method(alpha_2=country_name.upper())
                    elif lookup_method == pycountry.countries.search_fuzzy:
                        results = lookup_method(country_name)
                        if results: country_data = results[0]
                except Exception:
                    # Continue to next lookup_method if there's an error
                    continue
                
                if country_data: # Check outside the inner try-except
                    break # Break the for loop if country_data is found

            if country_data:
                phone_code_map = {
                    'ID': '+62', 'US': '+1', 'CA': '+1', 'GB': '+44', 'AU': '+61',
                    'MY': '+60', 'SG': '+65', 'TH': '+66', 'PH': '+63', 'VN': '+84',
                    'DE': '+49', 'FR': '+33', 'ES': '+34', 'IT': '+39', 'JP': '+81',
                    'KR': '+82', 'CN': '+86', 'RU': '+7', 'BR': '+55', 'IN': '+91',
                    'NZ': '+64', 'AE': '+971'
                }
                if country_data.alpha_2 in phone_code_map:
                    return phone_code_map[country_data.alpha_2]
                
        except Exception as e:
            print(f"[Debug] Error getting phone code for '{country_name}' with pycountry: {e}")
            pass
    
    wanbot_phone_code_info = get_wanbot_address_and_phone_info(country_name, None)
    if wanbot_phone_code_info and wanbot_phone_code_info.get('phone_number_example'):
        match = re.match(r'^\+(\d+)', wanbot_phone_code_info['phone_number_example'])
        if match:
            print(f"[Info] Kode telepon untuk '{country_name}' didapat dari Wanbot: +{match.group(1)}")
            return '+' + match.group(1)
        else:
            print(f"[Warning] Gagal ekstrak kode telepon dari contoh Wanbot: '{wanbot_phone_code_info['phone_number_example']}'")
    
    print(f"[Warning] Gagal menentukan kode telepon untuk '{country_name}'. Menggunakan default '+62'.")
    return "" # Mengembalikan string kosong jika tidak ditemukan, bukan None

def get_random_edge_user_agent():
    """Menghasilkan User-Agent string untuk browser Microsoft Edge di macOS."""
    # Versi Chrome/Edge Major (contoh: 134)
    major_version = random.randint(120, 135) 
    # Build version Chrome/Edge (contoh: 6791)
    build_version_chrome = random.randint(6000, 7000)
    # Patch version Chrome (contoh: 70)
    patch_version_chrome = random.randint(10, 150)
    # Build version Edge (contoh: 2764)
    build_version_edge = random.randint(2500, 3000)
    # Patch version Edge (contoh: 100)
    patch_version_edge = random.randint(50, 150)

    user_agent = (
        f"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_{random.randint(10,15)}_{random.randint(0,9)}) "
        f"AppleWebKit/537.36 (KHTML, like Gecko) "
        f"Chrome/{major_version}.0.{build_version_chrome}.{patch_version_chrome} "
        f"Safari/537.36 "
        f"Edg/{major_version}.0.{build_version_edge}.{patch_version_edge}"
    )
    return user_agent

# --- New function to handle 3DS verification ---
def handle_3ds_verification(driver, wait, chat_id, user_dir):
    """
    Handles 3DS verification pages.
    Tries to automate the specific Airwallex/Visa flow with retries for invalid codes.
    If it fails or encounters a different 3DS page, it falls back to manual user intervention.
    Returns True if verification is successful, False otherwise.
    """
    send_log(chat_id, "💳 *3DS Verification Detected!* 💳\n\n"
                     "Bot will attempt to automate this step. Please stand by...",
                     parse_mode='Markdown')

    time.sleep(5) # Give page and iframe time to load

    # --- Send screenshot as soon as 3DS is detected ---
    screenshot_path = save_screenshot(driver, user_dir, "3ds_initial_page")
    if screenshot_path:
        try:
            bot.send_photo(chat_id, open(screenshot_path, "rb"), caption="Screenshot of the detected 3DS verification page.")
        except Exception as e_ss:
            send_log(chat_id, f"❌ Failed to send 3DS screenshot: {e_ss}", is_error=True)

    # --- START: AUTOMATED 3DS FLOW ---
    try:
        # STEP 1: Switch to iframe and select verification method
        iframe_locator = (By.XPATH, "//iframe[starts-with(@id, 'cardinal-stepUpIframe')]")
        wait.until(EC.frame_to_be_available_and_switch_to_it(iframe_locator))
        send_log(chat_id, "✅ 3DS: Successfully switched to verification iframe.")

        # Check if we are on the selection page or directly on the code input page
        try:
            # --- NEW: Explicitly select the E-Mail option ---
            email_option_label_locator = (By.XPATH, "//label[normalize-space(.)='E-Mail']")
            email_option_label = WebDriverWait(driver, 5).until(EC.element_to_be_clickable(email_option_label_locator))
            click_with_mouse(driver, email_option_label)
            send_log(chat_id, "✅ 3DS: Explicitly selected 'E-Mail' as the verification method.")
            # --- END NEW ---

            continue_button_locator = (By.ID, "ContinueButton")
            continue_button = wait.until(EC.element_to_be_clickable(continue_button_locator))
            click_with_mouse(driver, continue_button)
            send_log(chat_id, "✅ 3DS: Clicked 'Continue' to request email OTP. Waiting for code input screen...")
        except TimeoutException:
            send_log(chat_id, "ℹ️ 3DS: 'Continue' button not found, assuming we are directly on the code input page.")
            pass # It's okay if it's not there, we might be on the input page already

        # STEP 2: Loop for OTP input and submission (to allow for retries)
        max_otp_retries = 3
        for attempt in range(1, max_otp_retries + 1):
            otp_input_locator = (By.ID, "CredentialValidateInput")
            wait.until(EC.presence_of_element_located(otp_input_locator))

            # Ask user for the code via Telegram
            markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
            markup.add(types.KeyboardButton('Batal'))
            prompt_message = (
                "📧 *Action Required:*\nPlease check your e-mail for the verification code and send the code here."
                if attempt == 1 else
                "⚠️ *Incorrect Code:*\nPlease re-enter the verification code. If you have a new one, use that."
            )
            msg = bot.send_message(chat_id, prompt_message, parse_mode='Markdown', reply_markup=markup)

            # Wait for user to send the code
            user_event = threading.Event()
            manual_input_data[chat_id] = {'event': user_event, 'value': None}
            user_event.wait(timeout=300) # 5 minute timeout

            user_response = manual_input_data[chat_id].get('value')
            del manual_input_data[chat_id]

            if not user_response or user_response.lower() == 'batal':
                send_log(chat_id, "❌ 3DS verification cancelled or timed out by user.", is_error=True)
                driver.switch_to.default_content()
                return False

            verification_code = user_response.strip()
            send_log(chat_id, f"✅ 3DS (Attempt {attempt}): Received code `{verification_code}`. Submitting...")

            # Input the code and submit
            otp_input_element = driver.find_element(*otp_input_locator)
            input_with_delay(otp_input_element, verification_code)

            submit_button_locator = (By.ID, "ValidateButton")
            submit_button = wait.until(EC.element_to_be_clickable(submit_button_locator))
            click_with_mouse(driver, submit_button)
            
            # Check for error message or success (redirect)
            time.sleep(3) # Wait for error message to appear
            try:
                error_message_locator = (By.ID, "ValidationErrorMessage")
                error_element = WebDriverWait(driver, 2).until(EC.visibility_of_element_located(error_message_locator))
                if "re-enter" in error_element.text:
                    if attempt < max_otp_retries:
                        continue # Loop to ask for the code again
                    else:
                        send_log(chat_id, "❌ 3DS: Invalid code entered multiple times. Aborting automated flow.", is_error=True)
                        raise TimeoutException("Max retries for OTP reached.") # Trigger fallback
            except TimeoutException:
                # No error message found, assume success and break the loop
                send_log(chat_id, "✅ 3DS: Verification code submitted. Waiting for redirect back to AWS...")
                break # Exit the retry loop

        # STEP 3: Wait for redirect back to AWS and for the SMS page to be ready
        driver.switch_to.default_content() # CRITICAL: Switch out of the iframe
        send_log(chat_id, "✅ 3DS: Code submitted. Waiting for page to redirect and load...")

        # Wait for an element that confirms we are on the SMS verification page
        # This is more reliable than just waiting for the URL.
        sms_page_ready_locator = (By.XPATH, "//*[contains(text(), 'Confirm your identity')]")
        wait.until(EC.visibility_of_element_located(sms_page_ready_locator))
        
        send_log(chat_id, "✅ Browser redirected and SMS verification page is loaded. 3DS verification successful.")
        return True

    except (TimeoutException, WebDriverException) as e:
        # --- FALLBACK: MANUAL 3DS FLOW ---
        send_log(chat_id, f"⚠️ Automated 3DS flow failed ({type(e).__name__}). Falling back to manual mode.")
        driver.switch_to.default_content() # Ensure we are not stuck in an iframe

        # The screenshot was already sent at the beginning of the function
        send_log(chat_id, "‼️ *MANUAL ACTION REQUIRED* ‼️\n\n"
                         "The bot could not automate this 3DS step. Please complete the verification process in the browser window *manually*.\n\n"
                         "‼️ *IMPORTANT*: Do NOT close the browser. "
                         "The bot will wait for you to complete this step.",
                         parse_mode='Markdown')
        
        # Offer options to the user
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        markup.add(types.KeyboardButton('✅ I have completed 3DS verification (redirected)'), types.KeyboardButton('❌ 3DS failed / Cancel'))
        
        bot.send_message(chat_id, "Please let me know once you have completed the 3DS verification in the browser.", 
                               reply_markup=markup)

        # Wait for user's manual confirmation
        user_event = threading.Event()
        manual_input_data[chat_id] = {'event': user_event, 'value': None}
        user_event.wait(timeout=300)

        user_response = manual_input_data[chat_id].get('value')
        del manual_input_data[chat_id]

        if user_response == '✅ I have completed 3DS verification (redirected)':
            send_log(chat_id, "✅ User confirmed 3DS completion. Checking browser status...")
            try:
                # Check if the URL has already changed back
                current_url = driver.current_url
                if "console.aws.amazon.com" in current_url or "portal.aws.amazon.com" in current_url:
                    send_log(chat_id, "✅ Browser is already on the AWS page. Verification assumed successful.")
                    return True
                else:
                    # If not, wait a bit longer for the redirect
                    wait.until(EC.url_contains("console.aws.amazon.com") or EC.url_contains("portal.aws.amazon.com/billing/signup"))
                    send_log(chat_id, "✅ Browser redirected back to AWS. 3DS verification assumed successful.")
                    return True
            except TimeoutException:
                send_log(chat_id, "❌ Timeout: Browser did not redirect back to AWS after confirmation. Verification might have failed.", is_error=True)
                save_screenshot(driver, user_dir, "3ds_manual_redirect_timeout")
                return False
        else:
            send_log(chat_id, "❌ 3DS verification cancelled or failed by user.", is_error=True)
            return False


# =============== ANTI CAPTCHA SOLVER (Diposisikan di atas karena dipanggil oleh solve_captcha_helper) =================

def anticaptcha_image_solver(image_bytes, api_key, chat_id=None):
    """Memecahkan captcha gambar menggunakan API Anti-Captcha."""
    create_task = {
        "clientKey": api_key,
        "task": {
            "type": "ImageToTextTask",
            "body": base64.b64encode(image_bytes).decode('utf-8')
        }
    }
    try:
        resp = requests.post("https://api.anti-captcha.com/createTask", json=create_task, timeout=10)
        resp.raise_for_status()
        task_info = resp.json()
        if task_info.get('errorId') != 0 or not task_info.get('taskId'):
            send_log(chat_id, f"[AntiCaptcha] Gagal membuat task captcha: {task_info.get('errorDescription', 'No error description')}", is_error=True)
            return None
        task_id = task_info['taskId']
        send_log(chat_id, f"[AntiCaptcha] Task dibuat dengan ID: {task_id}")

        # Tunggu hasil solve captcha
        for _ in range(40): # Maksimal sekitar 60 detik (40 * 1.5s)
            time.sleep(1.5)
            get_result = { "clientKey": api_key, "taskId": task_id }
            result_resp = requests.post("https://api.anti-captcha.com/getTaskResult", json=get_result, timeout=10)
            result_resp.raise_for_status()
            data = result_resp.json()

            if data.get('errorId') != 0:
                send_log(chat_id, f"[AntiCaptcha] Error saat mengambil hasil: {data.get('errorDescription', 'No error description')}", is_error=True)
                return None
            if data["status"] == "ready":
                hasil = data["solution"]["text"].strip()[:6] # Ambil maksimal 6 karakter
                send_log(chat_id, f"✅ *AntiCaptcha*: Captcha terpecahkan: `{hasil}`")
                return hasil
            elif data["status"] != "processing":
                send_log(chat_id, f"[AntiCaptcha] Status tidak diketahui atau error: {data['status']}", is_error=True)
                return None
        send_log(chat_id, "[AntiCaptcha] Timeout/gagal solve captcha setelah beberapa percobaan.", is_error=True)
        return None
    except requests.exceptions.RequestException as e:
        send_log(chat_id, f"[AntiCaptcha HTTP ERROR] {e}", is_error=True)
        return None
    except Exception as e:
        send_log(chat_id, f"[AntiCaptcha UNEXPECTED ERROR] {e}", is_error=True)
        return None

def solve_captcha_helper(driver, wait, chat_id, user_dir, anti_captcha_api_key, step_name):
    captcha_present = False
    captcha_iframe_locator = (By.ID, "core-container")
    max_iframe_checks = 3 # Número de vezes para verificar o iframe
    check_interval = 4 # Segundos entre as verificações

    for check_attempt in range(1, max_iframe_checks + 1):
        try:
            # Tente encontrar o iframe com um tempo de espera mais curto para cada tentativa
            wait_short_captcha = WebDriverWait(driver, 7)
            wait_short_captcha.until(EC.frame_to_be_available_and_switch_to_it(captcha_iframe_locator))
            
            # Se o iframe for encontrado, marque como presente e saia do loop de verificação
            captcha_present = True
            send_log(chat_id, f"🔄 *{step_name}*: Captcha detectado na tentativa {check_attempt}/{max_iframe_checks}. Tentando entrar no iframe...")
            break # Sai do loop for, pois o iframe foi encontrado

        except TimeoutException:
            # Se o iframe não for encontrado, registre e continue para a próxima tentativa (se houver)
            if check_attempt < max_iframe_checks:
                send_log(chat_id, f"⚠️ *{step_name}*: Captcha tidak detectado na tentativa {check_attempt}/{max_iframe_checks}. Verificando novamente em {check_interval} segundos...")
                time.sleep(check_interval)
            else:
                # Esta foi a última tentativa, então conclua que não há captcha
                send_log(chat_id, f"✅ *{step_name}*: Captcha tidak detectado após {max_iframe_checks} tentativas. Prosseguindo.")
                driver.switch_to.default_content() # Garante que estamos no conteúdo padrão
                return True # Retorna sucesso, pois não há captcha para resolver

        except Exception as e_iframe:
            send_log(chat_id, f"❌ *{step_name}*: Erro ao tentar mudar para o iframe do captcha: `{e_iframe}`. Voltando ao conteúdo padrão.", is_error=True)
            driver.switch_to.default_content()
            return False # Retorna falha, pois ocorreu um erro inesperado

    if captcha_present:
        max_captcha_retry = 5
        captcha_success = False
        for attempt in range(1, max_captcha_retry + 1):
            send_log(chat_id, f"🔄 *{step_name}*: Tentativa de resolver o CAPTCHA nº `{attempt}`/`{max_captcha_retry}`...")
            
            try:
                # O restante da lógica de resolução do CAPTCHA permanece o mesmo...
                # Try to find the CAPTCHA image element
                captcha_img_el = wait.until(EC.presence_of_element_located((By.XPATH, '//img[@alt="captcha"] | //img[contains(@class, "captcha-image")] | //img[contains(@src, "captcha")]')))
                
                captcha_src = captcha_img_el.get_attribute('src')
                if captcha_src is None:
                    send_log(chat_id, f"⚠️ *{step_name}*: O atributo 'src' da imagem CAPTCHA é None. O elemento pode estar incompleto ou ter mudado. Tentando novamente.")
                    save_screenshot(driver, user_dir, f"captcha_src_none_attempt_{attempt}")
                    try: # Try to reset CAPTCHA
                        reset_btn = wait.until(EC.element_to_be_clickable((By.XPATH, '//span[contains(@class,"awsui_label") and text()="Reset"]')))
                        click_with_mouse(driver, reset_btn)
                        send_log(chat_id, "✅ *Reset*: Botão de reset clicado com sucesso após src ser None.")
                        random_sleep(2,3)
                    except Exception as e_reset_none:
                        send_log(chat_id, f"❌ *{step_name}*: Falha ao encontrar ou clicar no botão de reset após src ser None: `{e_reset_none}`. Falha ao resolver o CAPTCHA.", is_error=True)
                        driver.switch_to.default_content()
                        return False
                    continue # Go to next attempt
                
                captcha_image_bytes = None
                if captcha_src.startswith('data:image'):
                    captcha_image_bytes = base64.b64decode(captcha_src.split(',')[1])
                else:
                    try:
                        send_log(chat_id, f"📥 *{step_name}*: Baixando imagem CAPTCHA...")
                        img_resp = requests.get(captcha_src, timeout=10)
                        img_resp.raise_for_status()
                        captcha_image_bytes = img_resp.content
                    except requests.exceptions.RequestException as e_img_download:
                        send_log(chat_id, f"❌ *{step_name}*: Falha ao baixar a imagem CAPTCHA: `{e_img_download}`. Tentando novamente.")
                        save_screenshot(driver, user_dir, f"captcha_download_error_attempt_{attempt}")
                        try: # Try to reset CAPTCHA
                            reset_btn = wait.until(EC.element_to_be_clickable((By.XPATH, '//span[contains(@class,"awsui_label") and text()="Reset"]')))
                            click_with_mouse(driver, reset_btn)
                            send_log(chat_id, "✅ *Reset*: Botão de reset clicado com sucesso após erro de download.")
                            random_sleep(2,3)
                        except Exception as e_reset_download:
                            send_log(chat_id, f"❌ *{step_name}*: Falha ao encontrar ou clicar no botão de reset após erro de download: `{e_reset_download}`. Falha ao resolver o CAPTCHA.", is_error=True)
                            driver.switch_to.default_content()
                            return False
                        continue # Go to next attempt

                if not captcha_image_bytes:
                    send_log(chat_id, f"⚠️ *{step_name}*: Imagem CAPTCHA vazia após o download. Tentando novamente.")
                    try: # Try to reset CAPTCHA
                        reset_btn = wait.until(EC.element_to_be_clickable((By.XPATH, '//span[contains(@class,"awsui_label") and text()="Reset"]')))
                        click_with_mouse(driver, reset_btn)
                        send_log(chat_id, "✅ *Reset*: Botão de reset clicado com sucesso após imagem vazia.")
                        random_sleep(2,3)
                    except Exception as e_reset_empty:
                        send_log(chat_id, f"❌ *{step_name}*: Falha ao encontrar ou clicar no botão de reset após imagem vazia: `{e_reset_empty}`. Falha ao resolver o CAPTCHA.", is_error=True)
                        driver.switch_to.default_content()
                        return False
                    continue # Go to next attempt
                
                captcha_text = anticaptcha_image_solver(captcha_image_bytes, anti_captcha_api_key, chat_id)
                
                if not captcha_text or len(captcha_text.strip()) < 4:
                    send_log(chat_id, f"⚠️ *{step_name}*: Anti-captcha falhou/resposta com menos de 4 caracteres. Tentando resetar o captcha.")
                    try:
                        reset_btn = wait.until(EC.element_to_be_clickable((By.XPATH, '//span[contains(@class,"awsui_label") and text()="Reset"]')))
                        click_with_mouse(driver, reset_btn)
                        random_sleep(2,3)
                    except Exception as e_reset:
                        send_log(chat_id, f"❌ *{step_name}*: Falha ao encontrar ou clicar no botão de reset após falha do Anti-Captcha: `{e_reset}`. Falha ao resolver o CAPTCHA.", is_error=True)
                        driver.switch_to.default_content()
                        return False
                    continue
                
                # Check for various possible input field locators for CAPTCHA
                captcha_input_locator = (By.CSS_SELECTOR, "input[type='text'][placeholder*='character'], input[type='text'][aria-label*='captcha'], input[type='text'][id*='formField']")
                input_field = wait.until(EC.presence_of_element_located(captcha_input_locator)) 
                input_with_delay(input_field, captcha_text)
                send_log(chat_id, f"✅ *{step_name}*: Texto do CAPTCHA inserido: `{captcha_text}`")
                random_sleep(1, 2)
                
                submit_btn = wait.until(EC.element_to_be_clickable((By.XPATH, '//button[span[text()="Submit"]]'))) 
                click_with_mouse(driver, submit_btn)
                time.sleep(2) # Short sleep to allow potential error message to appear

                # IMPORTANT: If CAPTCHA is wrong, click reset and retry, DO NOT exit function.
                error_message_locator = (By.XPATH, "//*[contains(@class, 'awsui_error') and (contains(text(), 'wasn’t quite right') or contains(text(), 'incorrect') or contains(text(), 'tidak cocok'))]")
                
                try:
                    error_elems = WebDriverWait(driver, 3).until(EC.presence_of_all_elements_located(error_message_locator))
                    if any(el.is_displayed() for el in error_elems):
                        send_log(chat_id, f"⚠️ *{step_name}*: CAPTCHA incorreto ('That wasn't quite right'). Procurando o botão de Reset para tentar novamente...")
                        save_screenshot(driver, user_dir, f"captcha_incorrect_attempt_{attempt}")
                        try:
                            reset_btn = wait.until(EC.element_to_be_clickable((By.XPATH, '//span[contains(@class,"awsui_label") and text()="Reset"]')))
                            click_with_mouse(driver, reset_btn)
                            send_log(chat_id, "✅ *Reset*: Botão de reset clicado com sucesso após CAPTCHA incorreto.")
                            random_sleep(2,3)
                        except Exception as e_reset_error:
                            send_log(chat_id, f"❌ *{step_name}*: Falha ao encontrar ou clicar no botão de Reset após CAPTCHA incorreto: `{e_reset_error}`. Falha ao resolver o CAPTCHA.", is_error=True)
                            driver.switch_to.default_content()
                            return False
                        continue # Continue to the next attempt in the loop
                except TimeoutException:
                    # If no error message after submit, means CAPTCHA was correct or navigation occurred
                    send_log(chat_id, f"✅ *{step_name}*: CAPTCHA aceito (nenhuma mensagem de erro detectada).")
                    captcha_success = True
                    break # Exit the captcha attempt loop because it was successful

            except TimeoutException: # This catches if the CAPTCHA image itself doesn't appear
                send_log(chat_id, f"❌ *{step_name}*: Timeout! A imagem CAPTCHA não foi encontrada no tempo especificado. Falha ao resolver o CAPTCHA.", is_error=True)
                save_screenshot(driver, user_dir, f"captcha_img_timeout_attempt_{attempt}")
                break # Exit the captcha attempt loop
            except StaleElementReferenceException:
                send_log(chat_id, f"⚠️ *{step_name}*: O elemento tornou-se obsoleto. Tentando recuperar o elemento dentro do iframe.")
                # Re-find captcha_img_el after stale error
                try:
                    captcha_img_el = wait.until(EC.presence_of_element_located((By.XPATH, '//img[@alt="captcha"] | //img[contains(@class, "captcha-image")] | //img[contains(@src, "captcha")]')))
                except Exception as e_re_find:
                    send_log(chat_id, f"❌ *{step_name}*: Falha ao reencontrar o elemento da imagem CAPTCHA após se tornar obsoleto: `{e_re_find}`. Falha ao resolver o CAPTCHA.", is_error=True)
                    driver.switch_to.default_content()
                    return False
                continue
            except Exception as e:
                send_log(chat_id, f"❌ *{step_name}*: ERRO ao resolver o CAPTCHA: `{e}`. Falha ao resolver o CAPTCHA.", is_error=True)
                save_screenshot(driver, user_dir, f"captcha_unexpected_error_attempt_{attempt}")
                break 
        
        driver.switch_to.default_content()
        return captcha_success
        
    return True # Se captcha_present era False, é considerado sucesso (sem captcha)

# =============== EMAIL OTP (Diposisikan di atas karena dipanggil oleh aws_signup_process) =================

def get_last_aws_otp(gmail_user, gmail_pass, chat_id=None, timeout=180, to_email_address=None):
    """Mencari OTP AWS terbaru dari inbox Gmail yang ditujukan ke to_email_address (jika diberikan)."""
    # If to_email_address is provided, use it for the IMAP search 'TO' criteria
    # Otherwise, fallback to the gmail_user itself (less specific but safer default)
    target_email_for_search = to_email_address if to_email_address else gmail_user

    send_log(chat_id, f"Mencari OTP AWS di email `{gmail_user}` (mencari email TO: `{target_email_for_search}`)...")
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            with IMAPClient('imap.gmail.com', ssl=True) as server:
                server.login(gmail_user, gmail_pass)
                server.select_folder('INBOX', readonly=True)
                
                # Search for emails from AWS within the last 15 minutes, AND TO the specific target_email_for_search
                fifteen_minutes_ago = time.time() - 900
                search_date_str = time.strftime("%d-%b-%Y", time.gmtime(fifteen_minutes_ago))

                search_criteria = ['FROM', 'no-reply@signup.aws', 'SINCE', search_date_str, 'TO', target_email_for_search]
                messages = server.search(search_criteria)
                
                if not messages:
                    send_log(chat_id, f"[Email] Tidak ada email dari AWS ditemukan dalam 15 menit terakhir yang ditujukan ke `{target_email_for_search}`. Menunggu...")
                    time.sleep(15)
                    continue

                # Process messages from newest to oldest
                for uid in reversed(messages[-5:]): # Check last 5 messages to avoid processing too many
                    raw_message_data = server.fetch([uid], ['BODY[]', 'ENVELOPE'])
                    if uid not in raw_message_data: continue
                    raw_message = raw_message_data[uid][b'BODY[]']
                    message_obj = pyzmail.PyzMessage.factory(raw_message)
                    subject = message_obj.get_subject()

                    patterns = [
                        r'Your AWS verification code is (\d{6})',
                        r'AWS account verification code: (\d{6})',
                        r'verifikasi.*?AWS.*?Anda adalah[:\s]*(\d{6})',
                        r'\b(\d{6})\b is your AWS verification code'
                    ]
                    for pattern in patterns:
                        match = re.search(pattern, subject, re.IGNORECASE)
                        if match:
                            otp = match.group(1)
                            send_log(chat_id, f"✅ *OTP AWS ditemukan di subject*: `{otp}`")
                            return otp
                    
                    generic_subject_otp = re.findall(r'\b\d{6}\b', subject)
                    if generic_subject_otp:
                        send_log(chat_id, f"✅ *OTP AWS generik ditemukan di subject*: `{generic_subject_otp[0]}`")
                        return generic_subject_otp[0]

                    body = ""
                    if message_obj.text_part:
                        payload = message_obj.text_part.get_payload()
                        body = payload.decode(message_obj.text_part.charset or 'utf-8', errors='replace') if isinstance(payload, bytes) else payload
                    elif message_obj.html_part:
                        payload = message_obj.html_part.get_payload()
                        body = payload.decode(message_obj.html_part.charset or 'utf-8', errors='replace') if isinstance(payload, bytes) else payload
                    
                    if body:
                        for pattern in patterns:
                            match = re.search(pattern, body, re.IGNORECASE)
                            if match:
                                otp = match.group(1)
                                send_log(chat_id, f"✅ *OTP AWS ditemukan di body*: `{otp}`")
                                return otp
                        generic_body_otp = re.findall(r'\b\d{6}\b', body)
                        if generic_body_otp:
                            send_log(chat_id, f"✅ *OTP AWS generik ditemukan di body*: `{generic_body_otp[0]}`")
                            return generic_body_otp[0]

        except LoginError:
            send_log(chat_id, "[OTP Email] Login Gagal! Periksa kredensial Gmail dan pastikan 'Less Secure App Access' diaktifkan atau gunakan App Password.", is_error=True)
            return None
        except Exception as e:
            send_log(chat_id, f"[OTP Email] ERROR: {e}", is_error=True)
        time.sleep(15)
    send_log(chat_id, f"[Email] OTP AWS tidak ditemukan setelah timeout untuk `{target_email_for_search}`!", is_error=True)
    return None

# =============== SMSHUB (Diposisikan di atas karena dipanggil oleh aws_signup_process) =================

def get_smshub_number_robust(api_key, country_id, operator_name, max_price, chat_id=None):
    """Mendapatkan nomor telepon dari SMSHub untuk layanan Amazon (am)."""
    send_log(chat_id, f"[SMSHub] Mencoba mendapatkan nomor {operator_name} (country_id={country_id}) untuk Amazon dengan harga maks {max_price}...")
    max_retry = 7
    retry_delay = 20 # detik
    for n in range(max_retry):
        try:
            # Menambahkan maxPrice ke URL
            url = f"http://smshub.org/stubs/handler_api.php?api_key={api_key}&action=getNumber&service=am&country={country_id}&operator={operator_name}&maxPrice={max_price}"
            resp = requests.get(url, timeout=20)
            resp.raise_for_status()
            hasil = resp.text.strip()

            if hasil.startswith("ACCESS_NUMBER"):
                _, id_req, number = hasil.split(":")
                send_log(chat_id, f"[SMSHub] Nomor diterima: {number} (ID: {id_req})")
                return id_req, number
            elif "NO_NUMBERS" in hasil:
                send_log(chat_id, f"⚠️ *SMSHub*: Tidak ada nomor `{operator_name}` yang tersedia saat ini dengan harga tersebut. Menunggu...")
            elif "BAD_KEY" in hasil:
                send_log(chat_id, "[SMSHub] API Key Salah.", is_error=True)
                return None, None
            elif any(err_msg in hasil for err_msg in ["NO_ACTIVATION", "BANNED", "ERROR_SQL"]):
                send_log(chat_id, f"[SMSHub] Error dari API: {hasil}. Mungkin ada masalah dengan akun/layanan SMSHub.", is_error=True)
                if "BANNED" in hasil: time.sleep(300) # Tunggu lebih lama jika di-ban
                else: time.sleep(60)
            else:
                send_log(chat_id, f"[SMSHub] Respon tidak dikenal: {hasil}. Menunggu...")
            time.sleep(retry_delay)
        except requests.exceptions.RequestException as e:
            send_log(chat_id, f"[SMSHub GetNum HTTP ERROR] {e}. Menunggu...", is_error=True)
            time.sleep(retry_delay)
        except Exception as e:
            send_log(chat_id, f"[SMSHub GetNum UNEXPECTED ERROR] {e}. Menunggu...", is_error=True)
            time.sleep(retry_delay)
    send_log(chat_id, "[SMSHub] Gagal mendapatkan nomor SMSHub setelah beberapa percobaan.", is_error=True)
    return None, None

def get_sms_otp(id_req, api_key, chat_id=None, max_wait=300):
    """Menunggu dan mengambil OTP SMS dari SMSHub berdasarkan ID permintaan."""
    url_base = f"http://smshub.org/stubs/handler_api.php?api_key={api_key}&action=getStatus&id={id_req}"
    send_log(chat_id, f"[SMSHub] Menunggu OTP untuk ID: {id_req} (maks {max_wait // 60} menit)...")
    start_time = time.time()
    while time.time() - start_time < max_wait:
        try:
            resp = requests.get(url_base, timeout=10)
            resp.raise_for_status()
            hasil = resp.text.strip()

            if "STATUS_OK" in hasil:
                otp = hasil.split(":")[1]
                send_log(chat_id, f"✅ *SMSHub] OTP diterima: {otp}")
                return otp
            elif "STATUS_WAIT_CODE" in hasil:
                pass # Menunggu
            elif any(err_status in hasil for err_status in ["STATUS_CANCEL", "WRONG_ACTIVATION_ID", "EARLY_CANCEL_DENIED"]):
                send_log(chat_id, f"[SMSHub] Status aktivasi tidak valid atau dibatalkan: {hasil}", is_error=True)
                return None
            else:
                send_log(chat_id, f"[SMSHub] Status OTP: {hasil}")
        except requests.exceptions.RequestException as e:
            send_log(chat_id, f"[SMSHub GetOTP HTTP ERROR] {e}", is_error=True)
        except Exception as e:
            send_log(chat_id, f"[SMSHub GetOTP UNEXPECTED ERROR] {e}", is_error=True)
        time.sleep(10) # Tunggu sebelum cek lagi
    
    send_log(chat_id, f"[SMSHub] Timeout menunggu OTP SMS untuk ID: {id_req}", is_error=True)
    # Coba batalkan nomor jika timeout
    try:
        requests.get(f"http://smshub.org/stubs/handler_api.php?api_key={api_key}&action=setStatus&status=8&id={id_req}", timeout=5)
        send_log(chat_id, f"[SMSHub] Nomor {id_req} dibatalkan setelah timeout OTP.")
    except Exception:
        pass # Abaikan jika pembatalan gagal
    return None

# =============== AWS SIGNUP PROCESS =================

def aws_signup_process(message):
    """Fungsi utama untuk mengotomatisasi proses pendaftaran AWS."""
    user_dir = get_user_dir(message)
    data = load_user_settings(message)
    chat_id = message.chat.id
    
    # Dapatkan atau buat event untuk pengguna ini
    stop_event = process_events.get(chat_id, threading.Event())
    stop_event.clear() # Pastikan event di-clear di awal
    process_events[chat_id] = stop_event

    def check_stop_event():
        """Memeriksa apakah proses harus dihentikan."""
        if stop_event.is_set():
            raise KeyboardInterrupt("Proses dihentikan oleh pengguna.")

    locale_code = get_faker_locale(data['country'])
    fake = Faker(locale_code)
    send_log(chat_id, f"🌐 *Faker*: Locale digunakan: `{locale_code}`")

    # Debug: Pastikan negara yang disimpan di settings sudah benar
    send_log(chat_id, f"DEBUG: Negara yang diambil dari pengaturan: `{data.get('country')}`")

    driver = None
    email = "" # This will store the generated email for AWS signup
    aws_account_name = ""
    full_name = ""
    address_line_1, city, state_province_data, postal_code = "", "", "", ""
    nomor_aus = ""
    last_sms_id = None

    def human_like_interaction(driver_instance):
        """Melakukan beberapa interaksi acak untuk simulasi manusia manusiawi."""
        try:
            check_stop_event()
            # Random scrolling
            scroll_amount = random.randint(100, 300)
            driver_instance.execute_script(f"window.scrollBy(0, {scroll_amount});")
            random_sleep(0.5, 1.0)
            driver_instance.execute_script(f"window.scrollBy(0, -{random.randint(50, 150)});")
            random_sleep(0.5, 1.0)

            # Move mouse to a random visible element
            elements = driver_instance.find_elements(By.XPATH, "//*[self::a or self::button or self::input or self::span or self::div][not(self::script or self::style)][string-length(normalize-space())>0 and @tabindex != '-1']")
            if elements:
                visible_elements = [el for el in elements if el.is_displayed() and el.is_enabled()]
                if visible_elements:
                    target_element = random.choice(visible_elements[:min(len(visible_elements), 10)])
                    actions = ActionChains(driver_instance)
                    actions.move_to_element(target_element).pause(random.uniform(0.2, 0.5)).perform()
                    random_sleep(0.5, 1.0)
        except KeyboardInterrupt:
            raise
        except Exception as e:
            print(f"[HumanLike] Error during human-like interaction: {e}")
            pass

    try:
        # --- [NEW] Handle Manual Email Input at the Start ---
        if data.get('email_mode') == 'Manual':
            markup_batal = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
            markup_batal.add(types.KeyboardButton('Batal'))
            bot.send_message(chat_id, "📧 *Mode Email Manual*: Silakan masukkan alamat email yang ingin Anda daftarkan ke AWS.", parse_mode='Markdown', reply_markup=markup_batal)
            
            user_event = threading.Event()
            manual_input_data[chat_id] = {'event': user_event, 'value': None}
            user_event.wait(timeout=300) # 5 menit timeout
            
            user_response = manual_input_data[chat_id].get('value')
            del manual_input_data[chat_id]
            
            if not user_response or user_response.lower() == 'batal':
                send_log(chat_id, "❌ *Proses Dibatalkan*: Pengguna tidak memasukkan email manual.", is_error=True)
                return
            
            # Simple validation
            if '@' not in user_response or '.' not in user_response.split('@')[-1]:
                send_log(chat_id, "❌ *Email Tidak Valid*: Format email yang Anda masukkan salah. Proses dihentikan.", is_error=True)
                return
            
            email = user_response.strip()
            data['manual_email'] = email # Simpan ke data untuk referensi
            send_log(chat_id, f"✅ *Email Manual Diterima*: `{email}`")
        # --- [END NEW] ---
        
        options = uc.ChromeOptions()
        user_agent = get_random_edge_user_agent()
        options.add_argument(f"user-agent={user_agent}")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--start-maximized")
        #options.add_argument("--headless=new") # Use 'new' headless mode for better compatibility
        options.add_argument("--incognito")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        # More anti-detection arguments
        options.add_argument("--disable-setuid-sandbox")
        options.add_argument("--disable-extensions")
        options.add_argument("--disable-features=IsolateOrigins,site-per-process")
        options.add_argument("--enable-automation") # This one is tricky, sometimes disabling is better, sometimes enabling hides it better. Let's try enabling.
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-browser-side-navigation")
        options.add_argument("--disable-infobars") # Disables the "Chrome is being controlled by automated test software" bar, but the underlying detection still happens.
        
        # --- Tambahkan argumen untuk menekan logging ChromeDriver/Chromium ---
        options.add_argument("--disable-logging")
        options.add_argument("--log-level=3") # Suppress logs below ERROR/FATAL

        # Logika inisialisasi driver dengan proxy
        proxy_string = data.get('proxy_string')
        use_proxy = data.get('use_proxy', False)

        # Set a higher default WebDriverWait timeout, especially crucial with proxies
        DEFAULT_WAIT_TIMEOUT = 45 # Increased from 30

        if use_proxy and proxy_string and webdriver_wire:
            send_log(chat_id, f"🔌 *Menggunakan Proxy*: `{proxy_string}`")
            
            proxy_parts = proxy_string.split(':')
            selenium_wire_options = {}
            
            if len(proxy_parts) == 2: # IP:PORT
                proxy_url = f"http://{proxy_parts[0]}:{proxy_parts[1]}"
            elif len(proxy_parts) == 4: # IP:PORT:USER:PASS
                proxy_url = f"http://{proxy_parts[2]}:{proxy_parts[3]}@{proxy_parts[0]}:{proxy_parts[1]}"
            else:
                send_log(chat_id, "❌ Format proxy tidak valid. Proses dihentikan.", is_error=True)
                return
            
            selenium_wire_options['proxy'] = {
                'http': proxy_url,
                'https': proxy_url,
                'no_proxy': 'localhost,127.0.0.1'
            }
            
            # Pass seleniumwire_options to webdriver_wire.Chrome
            # Note: service_log_path is not directly passed here, relying on --disable-logging
            driver = webdriver_wire.Chrome(options=options, seleniumwire_options=selenium_wire_options)

        else:
            if use_proxy and (not proxy_string or not webdriver_wire):
                send_log(chat_id, "⚠️ *Peringatan*: Proxy diaktifkan tetapi tidak diatur/modul `selenium-wire` tidak ditemukan. Menjalankan tanpa proxy.", is_error=True)
            else:
                send_log(chat_id, "🔌 *Tanpa Proxy*: Menjalankan dengan koneksi langsung.")
            
            # Note: service_log_path is not directly passed here, relying on --disable-logging
            driver = uc.Chrome(options=options) 
        
        # Apply higher default timeout
        wait = WebDriverWait(driver, DEFAULT_WAIT_TIMEOUT)

        send_log(chat_id, f"🌐 *Browser*: User-Agent digunakan: `{user_agent}`")
        send_log(chat_id, "🚀 *Memulai*: Membuka halaman AWS signup...")
        driver.get("https://signin.aws.amazon.com/signup?request_type=register")
        
        # Add human-like interaction after page load
        human_like_interaction(driver)
        random_sleep(2, 4)

        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "#emailAddress")))
        send_log(chat_id, "✅ *Halaman Dimuat*: Halaman signup AWS berhasil dimuat.")
        check_stop_event()

        # --- 1. Step: Email and Account Name ---
        send_log(chat_id, "--- *Langkah 1*: Pengaturan Email & Nama Akun ---")
        nama_mentah = fake.name()
        nama_bersih_parts = [re.sub(r'\W+', '', part) for part in nama_mentah.split()]
        nama_bersih = "".join(nama_bersih_parts).lower()
        if not nama_bersih:
            nama_bersih = fake.user_name()
            
        # [MODIFIED] Use manual email if set, otherwise generate random one
        if data.get('email_mode') != 'Manual':
            email = f"{nama_bersih}@{data['email_domain']}" # This is the generated email for AWS signup
        
        aws_account_name = f"{nama_bersih}"
        full_name = nama_mentah

        send_log(chat_id, f"🔄 *Data Dibuat*: Email: `{email}`, Nama Akun: `{aws_account_name}`")
        try:
            email_input_el = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "#emailAddress")))
            input_with_delay(email_input_el, email)
            random_sleep(0.5, 1.0)
            check_stop_event()

            account_name_input_el = driver.find_element(By.CSS_SELECTOR, "#accountName")
            input_with_delay(account_name_input_el, aws_account_name)
            random_sleep(1, 2)
            human_like_interaction(driver)
            random_sleep(1, 2)
            check_stop_event()

            btn_verify_email = driver.find_element(By.CSS_SELECTOR, "#__next > main > div:nth-child(2) > div > div > div.content-column_content-column__MXi7I > div > div > form > div > div > div.awsui_root_18582_lbexh_145.awsui_vertical_18582_lbexh_192.awsui_vertical-l_18582_lbexh_210 > div:nth-child(3) > button > span")
            
            send_log(chat_id, "➡️ *Navigasi*: Mengklik tombol 'Verify email address'...")
            click_with_mouse(driver, btn_verify_email) 
            
            # --- Panggil fungsi solve_captcha_helper di sini untuk CAPTCHA Email ---
            captcha_solved = solve_captcha_helper(driver, wait, chat_id, user_dir, data['anti_captcha_api_key'], "CAPTCHA Email (after email verify)")
            check_stop_event()

            if not captcha_solved:
                send_log(chat_id, "❌ *Signup Gagal*: Gagal mengatasi CAPTCHA setelah verifikasi email.", is_error=True)
                driver.quit()
                return

            # --- Deteksi dan interaksi dengan halaman OTP setelah CAPTCHA (atau jika tidak ada CAPTCHA) ---
            otp_found = False
            try:
                # Coba cari elemen OTP di main frame
                # Jika CAPTCHA disolve, driver sudah kembali ke default_content()
                otp_input_el = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "#otp")))
                otp_found = True
                send_log(chat_id, "✅ *Navigasi*: Berhasil maju ke halaman OTP email (di main frame).")
            except TimeoutException:
                # Jika tidak ditemukan di main frame, coba di iframe lain (jika ada, meskipun 'core-container' umumnya dipakai untuk CAPTCHA)
                send_log(chat_id, "🔍 *Pengecekan*: Elemen OTP tidak ditemukan di main frame. Mencoba mencari di iframe...")
                try:
                    # AWS mungkin punya iframe lain untuk OTP, atau OTP tetap di core-container.
                    # Kita coba lagi di core-container, mungkin CAPTCHA sudah hilang dan OTP muncul.
                    # Atau, ini mungkin menandakan struktur halaman berubah dan perlu inspeksi manual.
                    driver.switch_to.default_content() # Pastikan kembali ke main content sebelum mencoba iframe lagi
                    wait.until(EC.frame_to_be_available_and_switch_to_it((By.ID, "core-container"))) 
                    send_log(chat_id, "🔍 *Pengecekan*: Berhasil masuk kembali ke iframe 'core-container'. Mencari OTP di dalamnya.")
                    otp_input_el = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "#otp, input[name='otp'], input[inputmode='numeric'][pattern='[0-9]*']"))) # Locator lebih fleksibel
                    otp_found = True
                    send_log(chat_id, "✅ *Navigasi*: Berhasil maju ke halaman OTP email (di dalam iframe).")
                except TimeoutException:
                    send_log(chat_id, "❌ *Navigasi*: Elemen OTP tidak ditemukan di dalam iframe 'core-container' juga. Kembali ke main frame.")
                    driver.switch_to.default_content() # Penting: selalu kembali ke main content
                except Exception as e_iframe:
                    send_log(chat_id, f"❌ *Navigasi*: Error saat mencari OTP di iframe: `{e_iframe}`. Kembali ke main frame.", is_error=True)
                    driver.switch_to.default_content()

            if not otp_found:
                send_log(chat_id, "❌ *Navigasi*: Halaman OTP tidak muncul atau elemen OTP tidak ditemukan setelah verifikasi email. Proses dihentikan.", is_error=True)
                save_screenshot(driver, user_dir, "otp_page_not_found_after_email_verify")
                driver.quit()
                return # Exit immediately if critical navigation fails
            # --- Akhir Perbaikan Deteksi OTP ---

        except Exception as e:
            send_log(chat_id, f"❌ *Email/Nama*: ERROR di blok try utama: `{e}`", is_error=True)
            save_screenshot(driver, user_dir, f"email_step_error")
            driver.quit()
            return
        
        send_log(chat_id, f"✅ *Info Akun Awal*:\n"
                           f"  - Email: `{email}`\n"
                           f"  - Nama Akun AWS: `{aws_account_name}`\n"
                           f"  - Nama Lengkap: `{full_name}`")
        check_stop_event()

        # --- 2. Step: Email OTP Verification ---
        send_log(chat_id, "--- *Langkah 2*: Verifikasi OTP Email ---")
        
        # [MODIFIED] Branching logic for OTP retrieval
        otp_code = None
        if data.get('email_mode') == 'Manual':
            send_log(chat_id, f"🙋 *Aksi Diperlukan*: Bot menunggu Anda memasukkan kode OTP.")
            markup_batal = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
            markup_batal.add(types.KeyboardButton('Batal'))
            bot.send_message(chat_id, f"‼️ *AKSI DIPERLUKAN* ‼️\n\nSilakan periksa inbox email Anda (`{email}`) untuk kode verifikasi 6 digit dari AWS, lalu kirimkan kode tersebut ke sini.", parse_mode='Markdown', reply_markup=markup_batal)
            
            user_event = threading.Event()
            manual_input_data[chat_id] = {'event': user_event, 'value': None}
            user_event.wait(timeout=300) # 5 menit timeout
            
            user_response = manual_input_data[chat_id].get('value')
            del manual_input_data[chat_id]
            
            if not user_response or user_response.lower() == 'batal':
                send_log(chat_id, "❌ *Signup Gagal*: Verifikasi OTP manual dibatalkan atau timeout.", is_error=True)
                driver.quit()
                return
            
            otp_code = user_response.strip()
            if not (otp_code.isdigit() and len(otp_code) == 6):
                 send_log(chat_id, "❌ *Signup Gagal*: Kode OTP yang dimasukkan tidak valid (harus 6 digit angka).", is_error=True)
                 driver.quit()
                 return
        else: # Random (Automatic) mode
            send_log(chat_id, "⏳ *Menunggu*: Menunggu 10 detik agar email OTP AWS masuk ke inbox Gmail...") 
            time.sleep(10) # Initial wait for email to arrive
            check_stop_event()
            # This call will be attempted within the loop below
        
        # --- Common logic for submitting the OTP ---
        max_otp_email_retries = 3
        otp_email_verified = False

        for otp_attempt in range(1, max_otp_email_retries + 1):
            check_stop_event()
            send_log(chat_id, f"🔄 *OTP Email*: Percobaan verifikasi OTP email ke-`{otp_attempt}`/`{max_otp_email_retries}`...")

            # [MODIFIED] Get OTP code only if it's not already set by manual input
            if otp_code is None: # This will only be true for Random mode
                # Pass the generated email as to_email_address
                otp_code = get_last_aws_otp(data['gmail_user'], data['gmail_pass'], chat_id, timeout=120, to_email_address=email) 
            
            if not otp_code:
                send_log(chat_id, "⚠️ *OTP Email*: Gagal mengambil OTP email terbaru. Mencoba lagi...")
                if otp_attempt == max_otp_email_retries:
                    send_log(chat_id, "❌ *Signup Gagal*: Gagal mendapatkan OTP setelah beberapa kali coba.", is_error=True)
                    driver.quit()
                    return
                continue

            try:
                # Pastikan elemen OTP ditemukan lagi setelah mungkin ada navigasi/refresh
                current_otp_input_el = None
                try:
                    current_otp_input_el = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "#otp")))
                except TimeoutException:
                    try:
                        driver.switch_to.default_content() # Kembali ke main content dulu
                        wait.until(EC.frame_to_be_available_and_switch_to_it((By.ID, "core-container")))
                        current_otp_input_el = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "#otp, input[name='otp'], input[inputmode='numeric'][pattern='[0-9]*']")))
                    except Exception as e_re_switch:
                        send_log(chat_id, f"❌ *OTP Email*: Gagal menemukan elemen OTP setelah mencoba beralih frame: {e_re_switch}", is_error=True)
                        driver.switch_to.default_content() # Pastikan kembali ke main content
                        continue # Coba lagi di iterasi berikutnya

                if not current_otp_input_el:
                    send_log(chat_id, "❌ *OTP Email*: Elemen OTP tidak dapat ditemukan untuk diisi.", is_error=True)
                    driver.switch_to.default_content()
                    continue

                input_with_delay(current_otp_input_el, otp_code)
                random_sleep(0.8, 1.5)
                human_like_interaction(driver)
                random_sleep(0.8, 1.5)
                
                btn_otp_continue = driver.find_element(By.CSS_SELECTOR, "#__next > main > div:nth-child(2) > div > div > div.content-column_content-column__MXi7I > div > div > form > div > div > div:nth-child(2) > div:nth-child(2) > button > span")
                click_with_mouse(driver, btn_otp_continue)
                
                # Wait for password page to load, or error message to appear
                try:
                    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "#password")))
                    otp_email_verified = True
                    send_log(chat_id, "✅ *OTP Email*: Kode OTP email diterima dan diverifikasi.")
                    driver.switch_to.default_content() # Kembali ke main content setelah berhasil
                    break
                except TimeoutException:
                    incorrect_otp_msg = driver.find_elements(By.XPATH, "//div[contains(@class, 'awsui_content_mx3cw_ocy3i_390') and contains(text(), 'The verification code that you entered does not match our system')]")
                    if any(el.is_displayed() for el in incorrect_otp_msg):
                        send_log(chat_id, "⚠️ *OTP Email*: Kode OTP yang dimasukkan salah. Mencari kode terbaru...")
                        otp_code = None # Reset OTP code so it gets re-fetched/re-asked
                        save_screenshot(driver, user_dir, f"otp_email_incorrect_attempt_{otp_attempt}")
                        driver.switch_to.default_content() # Kembali ke main content setelah error
                    else:
                        send_log(chat_id, "⚠️ *OTP Email*: Tidak ada pesan error OTP tapi tidak maju ke halaman password. Mengulang...", is_error=True)
                        save_screenshot(driver, user_dir, f"otp_email_stuck_try_{otp_attempt}")
                        driver.switch_to.default_content() # Kembali ke main content
                        # Force refresh to get new CAPTCHA/state if stuck
                        driver.refresh()
                        time.sleep(5)
                        # The next iteration will re-find the OTP field
                        continue # Continue to next attempt
            except Exception as e:
                send_log(chat_id, f"❌ *OTP Email Input*: ERROR: `{e}`", is_error=True)
                save_screenshot(driver, user_dir, f"otp_email_input_error_attempt_{otp_attempt}")
                driver.switch_to.default_content() # Pastikan kembali ke main content
                break # Break and fail if inputting/clicking causes an error
        
        if not otp_email_verified:
            send_log(chat_id, "❌ *Signup Gagal*: Gagal memverifikasi OTP email setelah beberapa percobaan.", is_error=True)
            driver.quit()
            return

        # --- 3. Step: Password Setup ---
        send_log(chat_id, "--- *Langkah 3*: Pengaturan Password ---")
        try:
            check_stop_event()
            password_input_el = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "#password")))
            input_with_delay(password_input_el, data['root_password'])
            random_sleep(0.5, 1.0)
            check_stop_event()

            repassword_input_el = driver.find_element(By.CSS_SELECTOR, "#rePassword")
            input_with_delay(repassword_input_el, data['root_password'])
            random_sleep(1, 2)
            human_like_interaction(driver)
            random_sleep(1, 2)
            
            btn_pw_continue = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "button[data-testid='create-password-submit-button']")))
            click_with_mouse(driver, btn_pw_continue)
            
            # Wait for the contact info page to load
            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "#ContactInformation")))
            send_log(chat_id, "✅ *Password*: Password root berhasil diatur.")
        except Exception as e:
            send_log(chat_id, f"❌ *Password*: ERROR: `{e}`", is_error=True)
            save_screenshot(driver, user_dir, "password_step_error")
            driver.quit()
            return
        check_stop_event()

        # --- 4. Step: Contact Information (Alamat & Telepon) ---
        send_log(chat_id, "--- *Langkah 4*: Informasi Kontak (Alamat & Telepon) ---")
        
        wanbot_address_phone_info = get_wanbot_address_and_phone_info(data['country'], chat_id)

        if wanbot_address_phone_info and wanbot_address_phone_info.get('phone_number_example'):
            address_line_1 = wanbot_address_phone_info.get('street_address', fake.street_address())
            city = wanbot_address_phone_info.get('city', fake.city())
            state_province_data = wanbot_address_phone_info.get('state_province', fake.state() if hasattr(fake, 'state') else (fake.province() if hasattr(fake, 'province') else fake.city()))
            postal_code = wanbot_address_phone_info.get('postal_code', fake.postcode())
            nomor_aus = wanbot_address_phone_info['phone_number_example']
            send_log(chat_id, "✅ *Wanbot*: Menggunakan data alamat dan telepon dari Wanbot.")
        else:
            address_line_1 = fake.street_address()
            city = fake.city()
            state_province_data = fake.state() if hasattr(fake, 'state') else (fake.province() if hasattr(fake, 'province') else fake.city())
            postal_code = fake.postcode()
            nomor_aus = fake.phone_number()
            send_log(chat_id, "⚠️ *Wanbot*: Gagal mendapatkan data dari Wanbot. Menggunakan data from Faker.")

        try:
            check_stop_event()
            personal_radio = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "#awsui-radio-button-2-label > div.awsui-radio-button-content > div > span > span > span")))
            click_with_mouse(driver, personal_radio)
            random_sleep(0.8, 1.5)
            send_log(chat_id, "✅ *Kontak*: Memilih tipe akun 'Personal'.")
            
            full_name_contact_el = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "#awsui-input-0")))
            input_with_delay(full_name_contact_el, full_name)
            random_sleep(0.8, 1.5)
            
            country_dropdown_contact = driver.find_element(By.CSS_SELECTOR, "#awsui-select-0 > div > awsui-icon > span")
            click_with_mouse(driver, country_dropdown_contact)
            random_sleep(0.8, 1.5)
            
            # --- Perbaikan pemilihan negara di dropdown ---
            selected_country_text = data['country'] # Negara yang harus dipilih
            country_option_contact_found = False
            
            # Coba cari berdasarkan teks persis atau variasi umum
            country_options_locators = [
                (By.XPATH, f"//span[normalize-space(text())='{selected_country_text}']"), # Contoh: 'Finlandia'
                (By.XPATH, f"//span[normalize-space(text())='{selected_country_text.split()[0]}']"), # Contoh: 'Finland' dari 'Finlandia'
                (By.XPATH, f"//span[contains(normalize-space(text()),'{selected_country_text}')]"), # Contoh: 'United States of America' jika user input 'United States'
                (By.XPATH, f"//span[contains(normalize-space(text()),'United States') or contains(normalize-space(text()),'USA')]"), # Untuk US/USA
                (By.XPATH, f"//span[contains(normalize-space(text()),'United Kingdom') or contains(normalize-space(text()),'UK')]") # Untuk UK/Great Britain
            ]

            # First, try to find the search input within the dropdown
            search_input_el = None
            try:
                # Locator untuk input pencarian di dropdown bisa bervariasi, sesuaikan jika perlu
                search_input_el = WebDriverWait(driver, 5).until(EC.element_to_be_clickable((By.CSS_SELECTOR, "input[role='combobox'][autocomplete='off']")))
                input_with_delay(search_input_el, selected_country_text)
                send_log(chat_id, f"✅ *Kontak*: Mencari negara `{selected_country_text}` di dropdown...")
                random_sleep(1, 2) # Give time for results to filter
            except TimeoutException:
                send_log(chat_id, "ℹ️ *Kontak*: Input pencarian di dropdown tidak ditemukan, mencoba klik langsung opsi.")
            except Exception as e_search_input:
                send_log(chat_id, f"⚠️ *Kontak*: Error saat mengisi input pencarian di dropdown: `{e_search_input}`. Mencoba klik langsung opsi.")

            # Then, try to click the filtered/direct option
            for locator in country_options_locators:
                try:
                    country_option_contact = wait.until(EC.element_to_be_clickable(locator))
                    click_with_mouse(driver, country_option_contact)
                    country_option_contact_found = True
                    send_log(chat_id, f"✅ *Kontak*: Negara `{selected_country_text}` berhasil dipilih.")
                    break
                except TimeoutException:
                    pass # Coba locator berikutnya
                except Exception as e_select:
                    send_log(chat_id, f"⚠️ *Kontak*: Gagal memilih negara dengan locator `{locator[1]}`: `{e_select}`. Mencoba yang lain.")
                    pass

            if not country_option_contact_found:
                send_log(chat_id, f"❌ *Kontak*: Negara `{selected_country_text}` tidak ditemukan di dropdown AWS. Pastikan nama negara sudah benar. Proses dihentikan.", is_error=True)
                save_screenshot(driver, user_dir, "country_selection_failed")
                driver.quit()
                return
            # --- Akhir Perbaikan pemilihan negara di dropdown ---

            random_sleep(0.8, 1.5)
            
            phone_country_dropdown_initial = driver.find_element(By.CSS_SELECTOR, "#awsui-select-1 > div > awsui-icon > span")
            click_with_mouse(driver, phone_country_dropdown_initial)
            random_sleep(0.8, 1.5)
                
            # --- Perbaikan pemilihan kode negara telepon di dropdown ---
            phone_country_option_found = False
            search_input_el_phone = None
            try:
                # Locator untuk input pencarian di dropdown phone code (berdasarkan id yang Anda berikan)
                search_input_el_phone = WebDriverWait(driver, 5).until(EC.element_to_be_clickable((By.CSS_SELECTOR, "input[id='awsui-input-1'][autocomplete='off'][role='combobox']")))
                # Pastikan elemen input pencarian sudah *interactable*
                WebDriverWait(driver, 5).until(EC.element_to_be_clickable(search_input_el_phone))
                input_with_delay(search_input_el_phone, selected_country_text)
                send_log(chat_id, f"✅ *Kontak*: Mencari kode negara telepon `{selected_country_text}` di dropdown...")
                random_sleep(1, 2) # Give time for results to filter
            except TimeoutException:
                send_log(chat_id, "ℹ️ *Kontak*: Input pencarian di dropdown kode telepon tidak ditemukan, mencoba klik langsung opsi.")
            except Exception as e_search_input_phone:
                send_log(chat_id, f"⚠️ *Kontak*: Error saat mengisi input pencarian di dropdown kode telepon: `{e_search_input_phone}`. Mencoba klik langsung opsi.")

            for locator in country_options_locators: # Re-use locators from contact info
                try:
                    country_option_phone_initial = wait.until(EC.element_to_be_clickable(locator))
                    click_with_mouse(driver, country_option_phone_initial)
                    phone_country_option_found = True
                    send_log(chat_id, f"✅ *Kontak*: Kode negara telepon `{selected_country_text}` berhasil dipilih.")
                    break
                except TimeoutException:
                    pass
                except Exception as e_select_phone:
                    send_log(chat_id, f"⚠️ *Kontak*: Gagal memilih kode negara telepon dengan locator `{locator[1]}`: `{e_select_phone}`. Mencoba yang lain.")
                    pass
            
            if not phone_country_option_found:
                send_log(chat_id, f"❌ *Kontak*: Kode negara telepon untuk `{selected_country_text}` tidak ditemukan di dropdown AWS. Proses dihentikan.", is_error=True)
                save_screenshot(driver, user_dir, "phone_country_selection_failed")
                driver.quit()
                return
            # --- Akhir Perbaikan pemilihan kode negara telepon di dropdown ---

            random_sleep(0.8, 1.5)

            address_el = driver.find_element(By.CSS_SELECTOR, "#awsui-input-3")
            input_with_delay(address_el, address_line_1)
            city_el = driver.find_element(By.CSS_SELECTOR, "#awsui-input-5")
            input_with_delay(city_el, city)
            state_el = driver.find_element(By.CSS_SELECTOR, "#awsui-input-6")
            input_with_delay(state_el, state_province_data)
            postal_code_el = driver.find_element(By.CSS_SELECTOR, "#awsui-input-7")
            input_with_delay(postal_code_el, postal_code)
            
            send_log(chat_id, f"✅ *Kontak*: Alamat diisi: `{address_line_1}, {city}, {state_province_data}, {postal_code}, {data['country']}`")
            human_like_interaction(driver)
            random_sleep(1, 2)

            agree_checkbox = driver.find_element(By.CSS_SELECTOR, "#awsui-checkbox-0")
            if not agree_checkbox.is_selected():
                 click_with_mouse(driver, agree_checkbox)
            random_sleep(0.8,1.5)
            send_log(chat_id, "✅ *Kontak*: Checkbox persetujuan dicentang.")

            success_phone = False
            max_tries_phone_input = 10
            for attempt in range(max_tries_phone_input):
                if attempt != 0:
                    send_log(chat_id, f"⚠️ *Kontak*: Nomor `{nomor_aus}` tidak valid. Mencoba nomor baru (Percobaan `{attempt+1}`/`{max_tries_phone_input}`)...")
                    driver.find_element(By.CSS_SELECTOR, "#awsui-input-2").clear()

                    new_wanbot_info_for_phone = get_wanbot_address_and_phone_info(data['country'], chat_id)
                    if new_wanbot_info_for_phone and new_wanbot_info_for_phone.get('phone_number_example'):
                        nomor_aus = new_wanbot_info_for_phone['phone_number_example']
                        send_log(chat_id, "✅ *Kontak*: Menggunakan nomor baru dari Wanbot.")
                    else:
                        nomor_aus = fake.phone_number()
                        send_log(chat_id, "⚠️ *Kontak*: Wanbot gagal memberikan nomor baru. Menggunakan data from Faker.")
                
                phone_input_initial = driver.find_element(By.CSS_SELECTOR, "#awsui-input-2")
                input_with_delay(phone_input_initial, nomor_aus)
                random_sleep(0.8, 1.5)

                continue_contact_button = driver.find_element(By.CSS_SELECTOR, "#ContactInformation > fieldset > awsui-button > button > span")
                click_with_mouse(driver, continue_contact_button)
                
                # Wait for either payment info or phone error
                try:
                    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "#PaymentInformation")))
                    success_phone = True
                    break
                except TimeoutException:
                    errors = driver.find_elements(By.XPATH, "//div[contains(@class, 'awsui_content_mx3cw_14ina_390') and contains(text(), 'phone number provided is not valid')]")
                    if not errors:
                        send_log(chat_id, "⚠️ *Kontak*: Tidak ada error telepon tapi tidak maju ke halaman pembayaran. Mengulang...", is_error=True)
                        save_screenshot(driver, user_dir, f"phone_input_stuck_attempt_{attempt}")
                        # Force refresh or retry current step logic
                        continue # Continue to next attempt
                    
                send_log(chat_id, f"⚠️ *Kontak*: Nomor `{nomor_aus}` masih tidak valid. Mencoba lagi...")
                random_sleep(1, 2)
            
            if not success_phone:
                send_log(chat_id, "❌ *Signup Gagal*: Gagal mendapatkan nomor telepon valid setelah beberapa percobaan.", is_error=True)
                driver.quit()
                return
            send_log(chat_id, f"✅ *Kontak*: Nomor HP yang dimasukkan: `{nomor_aus}`.")

        except Exception as e:
            send_log(chat_id, f"❌ *Alamat/Kontak*: ERROR: `{e}`", is_error=True)
            save_screenshot(driver, user_dir, "contact_info_error")
            driver.quit()
            return

        # --- 5. Step: Payment Information ---
        send_log(chat_id, "--- *Langkah 5*: Informasi Pembayaran ---")
        
        try:
            check_stop_event()
            billing_country_dropdown = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "#awsui-select-2 > div > awsui-icon > span")))
            click_with_mouse(driver, billing_country_dropdown)
            random_sleep(0.8, 1.5)
            
            # --- Perbaikan pemilihan negara billing di dropdown ---
            billing_country_option_found = False
            search_input_el_billing = None
            try:
                # Locator untuk input pencarian di dropdown billing
                search_input_el_billing = WebDriverWait(driver, 5).until(EC.element_to_be_clickable((By.CSS_SELECTOR, "input[role='combobox'][autocomplete='off']")))
                # Pastikan elemen input pencarian sudah *interactable*
                WebDriverWait(driver, 5).until(EC.element_to_be_clickable(search_input_el_billing))
                input_with_delay(search_input_el_billing, selected_country_text)
                send_log(chat_id, f"✅ *Pembayaran*: Mencari negara billing `{selected_country_text}` di dropdown...")
                random_sleep(1, 2) # Give time for results to filter
            except TimeoutException:
                send_log(chat_id, "ℹ️ *Pembayaran*: Input pencarian di dropdown billing tidak ditemukan, mencoba klik langsung opsi.")
            except Exception as e_search_input_billing:
                send_log(chat_id, f"⚠️ *Pembayaran*: Error saat mengisi input pencarian di dropdown billing: `{e_search_input_billing}`. Mencoba klik langsung opsi.")

            for locator in country_options_locators: # Re-use locators from contact info
                try:
                    billing_country_option = wait.until(EC.element_to_be_clickable(locator))
                    click_with_mouse(driver, billing_country_option)
                    billing_country_option_found = True
                    send_log(chat_id, f"✅ *Pembayaran*: Negara billing `{selected_country_text}` berhasil dipilih.")
                    break
                except TimeoutException:
                    pass
                except Exception as e_select_billing:
                    send_log(chat_id, f"⚠️ *Pembayaran*: Gagal memilih negara billing dengan locator `{locator[1]}`: `{e_select_billing}`. Mencoba yang lain.")
                    pass

            if not billing_country_option_found:
                send_log(chat_id, f"❌ *Pembayaran*: Negara billing `{selected_country_text}` tidak ditemukan di dropdown AWS. Proses dihentikan.", is_error=True)
                save_screenshot(driver, user_dir, "billing_country_selection_failed")
                driver.quit()
                return
            # --- Akhir Perbaikan pemilihan negara billing di dropdown ---

            random_sleep(0.8, 1.5)
            check_stop_event()
            
            cc_number_el = driver.find_element(By.CSS_SELECTOR, "#awsui-input-10")
            input_with_delay(cc_number_el, data['credit_card'])
            random_sleep(0.8, 1.5)
            
            expiry_month_dropdown = driver.find_element(By.CSS_SELECTOR, "#awsui-select-3 > div > awsui-icon > span")
            click_with_mouse(driver, expiry_month_dropdown)
            random_sleep(0.8, 1.5)
            
            month_option = wait.until(EC.element_to_be_clickable((By.XPATH, f"//span[contains(@class, 'awsui-select-option-label') and text()='{data['month']}']")))
            click_with_mouse(driver, month_option)
            random_sleep(0.8, 1.5)
            
            expiry_year_dropdown = driver.find_element(By.CSS_SELECTOR, "#awsui-select-4 > div > awsui-icon > span")
            click_with_mouse(driver, expiry_year_dropdown)
            random_sleep(0.8, 1.5)
            
            year_option = wait.until(EC.element_to_be_clickable((By.XPATH, f"//span[contains(@class, 'awsui-select-option-label') and text()='{data['year']}']")))
            click_with_mouse(driver, year_option)
            random_sleep(0.8, 1.5)

            send_log(chat_id, "🔄 *Pembayaran*: Mencoba mengisi CVV jika field tersedia...")
            try:
                cvv_el = WebDriverWait(driver, 5).until(EC.presence_of_element_located((By.CSS_SELECTOR, "#awsui-input-11")))
                if cvv_el.is_displayed() and cvv_el.is_enabled():
                    cvv_to_fill = data.get('cvv', '').strip()
                    if not cvv_to_fill or cvv_to_fill == '0':
                        final_cvv = '000'
                        send_log(chat_id, "ℹ️ *Pembayaran*: CVV tidak di-set atau '0', menggunakan '000' sebagai default.")
                    elif not (cvv_to_fill.isdigit() and (3 <= len(cvv_to_fill) <= 4)):
                        send_log(chat_id, f"⚠️ *Pembayaran*: CVV '{cvv_to_fill}' tidak valid, menggunakan '000' sebagai gantinya.")
                        final_cvv = '000'
                    else:
                        final_cvv = cvv_to_fill

                    input_with_delay(cvv_el, final_cvv)
                    send_log(chat_id, f"✅ *Pembayaran*: CVV diisi dengan: `{final_cvv}`")
                else:
                    send_log(chat_id, "ℹ️ *Pembayaran*: Input field CVV tidak ditemukan atau tidak interaktif.")
            except Exception as e_cvv:
                send_log(chat_id, f"ℹ️ *Pembayaran*: Tidak dapat mengisi CVV (mungkin opsional atau ID berubah): `{e_cvv}`")
            random_sleep(0.5, 1.0)
            
            cardholder_name_el = driver.find_element(By.CSS_SELECTOR, "#awsui-input-12")
            input_with_delay(cardholder_name_el, full_name)
            random_sleep(1, 2)
            send_log(chat_id, f"✅ *Pembayaran*: Nama Pemegang Kartu diisi: `{full_name}`")
            human_like_interaction(driver)
            random_sleep(1, 2)

            btn_payment_continue = driver.find_element(By.CSS_SELECTOR, "#PaymentInformation > fieldset > awsui-button > button > span")
            click_with_mouse(driver, btn_payment_continue)

            send_log(chat_id, "✅ *Pembayaran*: Informasi pembayaran dikirim. Memeriksa halaman selanjutnya...")
            
        except Exception as e:
            send_log(chat_id, f"❌ *Pembayaran*: ERROR: `{e}`", is_error=True)
            save_screenshot(driver, user_dir, "payment_step_error")
            driver.quit()
            return
        
        # --- Smart Page Detection After Payment (Crucial for Detection) ---
        page_status_after_payment = "unknown"
        send_log(chat_id, "⏳ *Menunggu Halaman Selanjutnya*: Memberi waktu hingga 45 detik untuk halaman pembayaran dimuat...")

        # Use EC.any_of to wait for any of the expected outcomes
        try:
            check_stop_event()
            wait.until(
                EC.any_of(
                    EC.presence_of_element_located((By.XPATH, "//button/span[contains(text(), 'Call me now')]")), # Bot detection
                    EC.url_contains("client.cardinaltrusted.com"), # 3DS Verification
                    EC.url_contains("payments-verification"), # External VCC/Bank verification
                    EC.url_contains("challenge"), # External VCC/Bank verification
                    EC.url_contains("hooks.stripe.com"), # External VCC/Bank verification
                    EC.presence_of_element_located((By.XPATH, "//span[contains(text(), 'Text message (SMS)')]")), # SMS verification page
                    EC.presence_of_element_located((By.XPATH, "//*[contains(text(), 'payment method cannot be verified')]")) # NEW: Direct payment failure
                )
            )
            current_url = driver.current_url

            # --- CHECK FOR IMMEDIATE PAYMENT FAILURE ---
            try:
                payment_error_locator = (By.XPATH, "//*[contains(@class, 'awsui_content') and contains(text(), 'The payment method cannot be verified')]")
                error_element = WebDriverWait(driver, 2).until(EC.visibility_of_element_located(payment_error_locator))
                if error_element:
                    error_message = (
                        "❌ *Falha na Verificação do Pagamento!* ❌\n\n"
                        "A AWS não conseguiu verificar seu método de pagamento. Isso geralmente significa que o VCC/cartão foi rejeitado.\n\n"
                        "*Soluções:*\n"
                        "1. Tente um VCC/cartão diferente.\n"
                        "2. Verifique se o cartão tem saldo e está habilitado para transações internacionais/online.\n"
                        "3. Considere usar um cartão de um país diferente."
                    )
                    screenshot_path = save_screenshot(driver, user_dir, "payment_method_rejected")
                    send_log(chat_id, error_message, parse_mode='Markdown', is_error=True, photo_path=screenshot_path)
                    driver.quit()
                    return # Stop the process
            except TimeoutException:
                pass # No immediate error, continue checks

            # PRIORITAS 1: Cek deteksi BOT (Call me now)
            call_me_button_elements = driver.find_elements(By.XPATH, "//button/span[contains(text(), 'Call me now')]")
            if call_me_button_elements and call_me_button_elements[0].is_displayed():
                print("[DETECTION] Halaman verifikasi 'Call me now' terdeteksi.")
                filename_bot_detected = save_screenshot(driver, user_dir, "bot_detection_after_payment")
                send_log(chat_id, BOT_DETECTION_MESSAGE, parse_mode='Markdown', is_error=True, photo_path=filename_bot_detected)
                page_status_after_payment = "bot_detected"

            # PRIORITAS 2: Cek página de verificação 3DS Cardinal
            elif "client.cardinaltrusted.com" in current_url:
                send_log(chat_id, "💳 Pagamento: Página de verificação 3DS Cardinal detectada. Iniciando o fluxo de verificação...")
                is_3ds_successful = handle_3ds_verification(driver, wait, chat_id, user_dir)

                if is_3ds_successful:
                    # A função handle_3ds_verification agora garante que a página de SMS está carregada.
                    # Podemos verificar imediatamente se há erros ou prosseguir.
                    send_log(chat_id, "🔍 Verificando o status após o retorno do 3DS...")
                    time.sleep(2) # Pequena pausa para estabilizar

                    try:
                        # Check for the "payment method cannot be verified" error
                        payment_error_locator = (By.XPATH, "//*[contains(@class, 'awsui_content') and contains(text(), 'The payment method cannot be verified')]")
                        error_element = WebDriverWait(driver, 5).until(EC.visibility_of_element_located(payment_error_locator))
                        if error_element:
                            error_message = (
                                "❌ Falha na Verificação do Pagamento (Pós-3DS)! ❌\n\n"
                                "Mesmo após a verificação 3DS bem-sucedida, a AWS rejeitou o método de pagamento.\n\n"
                                "*Soluções:*\n"
                                "1. Tente um VCC/cartão diferente.\n"
                                "2. O cartão pode ter sido sinalizado pela AWS."
                            )
                            screenshot_path = save_screenshot(driver, user_dir, "payment_method_rejected_post_3ds")
                            send_log(chat_id, error_message, parse_mode='Markdown', is_error=True, photo_path=screenshot_path)
                            driver.quit()
                            return # Stop the process
                    except TimeoutException:
                        # No error found, it's safe to assume we are on the SMS page
                        send_log(chat_id, "✅ Verificação pós-3DS bem-sucedida. Prosseguindo para a verificação por SMS.")
                        page_status_after_payment = "sms_page"
                else:
                    # handle_3ds_verification returned False
                    page_status_after_payment = "3ds_failed"


            # PRIORITAS 3: Cek página de verificação VCC/Banco externa
            elif "payments-verification" in current_url or "challenge" in current_url or "hooks.stripe.com" in current_url:
                # This logic for manual approval remains the same
                send_log(chat_id, "⏳ *Pagamento*: Página de verificação de VCC/Banco detectada. Aguardando sua aprovação... (tirando screenshot em 20 segundos)")
                # ... (o resto da sua lógica para este caso permanece o mesmo) ...

            # PRIORITAS 4: Cek página de verificação por SMS
            elif driver.find_elements(By.XPATH, "//span[contains(text(), 'Text message (SMS)')]"):
                send_log(chat_id, "✅ *Navegação*: Página de verificação por SMS detectada diretamente.")
                page_status_after_payment = "sms_page"

            # Se nenhuma das condições acima corresponder
            else:
                filename_unknown = save_screenshot(driver, user_dir, "after_payment_page")
                send_log(chat_id, "⚠️ *Navegação*: Página após o pagamento desconhecida. Screenshot tirado para análise.", is_error=True, photo_path=filename_unknown)
                page_status_after_payment = "unknown_page_after_payment"

        except TimeoutException: # This TimeoutException is from the initial EC.any_of
            current_url = driver.current_url
            filename_after_payment = save_screenshot(driver, user_dir, "after_payment_page_timeout")
            send_log(chat_id, f"❌ *Navegação*: Timeout! Nenhuma página reconhecida após o pagamento. URL Atual: `{current_url}`.", is_error=True, photo_path=filename_after_payment)
            page_status_after_payment = "timeout_after_payment_generic"
        except Exception as e: # Catch all other errors during initial detection
            current_url = driver.current_url
            filename_after_payment = save_screenshot(driver, user_dir, "error_detection_after_payment")
            send_log(chat_id, f"❌ *Navegação*: Erro ao analisar a página após o pagamento: `{e}`. URL Atual: `{current_url}`.", is_error=True, photo_path=filename_after_payment)
            page_status_after_payment = "error_detection_after_payment"

        # Continue or stop the process based on detected status
        if page_status_after_payment == "sms_page":
            send_log(chat_id, "➡️ *Continuar*: Prosseguindo para o processo de verificação por SMS...")
        else:
            # This will now correctly handle the new failure cases
            if driver:
                driver.quit()
            return
        check_stop_event()

        # --- 6. Step: Phone Verification (SMS OTP) ---
        send_log(chat_id, "--- *Langkah 6*: Verifikasi Identitas (Telepon SMS) ---")
        
        send_log(chat_id, "🔄 *Refresh*: Merefresh halaman verifikasi untuk memastikan elemen termuat dengan baik.")
        driver.refresh()
        time.sleep(5) # Give browser time to refresh and load
        human_like_interaction(driver)
        random_sleep(2, 4)

        try:
            # Re-check for 'Call me now' button after refresh, this is the main bot detection point
            call_me_button_check_after_refresh = driver.find_elements(By.XPATH, "//button/span[contains(text(), 'Call me now')]")
            if call_me_button_check_after_refresh and call_me_button_check_after_refresh[0].is_displayed():
                print("[DETECTION] Halaman verifikasi 'Call me now' terdeteksi setelah refresh.")
                filename_bot_detected = save_screenshot(driver, user_dir, "bot_detection_after_refresh")
                
                send_log(chat_id, BOT_DETECTION_MESSAGE, parse_mode='Markdown', is_error=True, photo_path=filename_bot_detected) 
                
                driver.quit()
                return
            
            # If no bot detected, continue looking for SMS elements
            wait.until(EC.presence_of_element_located((By.XPATH, "//span[contains(text(), 'Text message (SMS)')]")))
            send_log(chat_id, "✅ *Navigasi*: Halaman verifikasi SMS siap untuk interaksi.")

        except TimeoutException:
            send_log(chat_id, f"❌ *Navigasi*: Timeout! Halaman verifikasi SMS tidak muncul atau elemen 'Text message (SMS)' tidak ditemukan setelah refresh.", is_error=True, photo_path=save_screenshot(driver, user_dir, "sms_page_timeout_after_refresh"))
            driver.quit()
            return
        except Exception as e_check:
            send_log(chat_id, f"❌ *Navigasi*: Error tak terduga saat memeriksa halaman verifikasi SMS setelah refresh: `{e_check}`", is_error=True, photo_path=save_screenshot(driver, user_dir, "error_after_sms_refresh"))
            driver.quit()
            return
        check_stop_event()

        max_phone_otp_attempts = 3
        phone_otp_success = False
        
        smshub_country_name_for_aws_dropdown = data.get('smshub_country_name')
        target_country_code_aws = get_country_phone_code(smshub_country_name_for_aws_dropdown)
        send_log(chat_id, f"🌐 *Phone OTP*: Target kode telepon AWS untuk negara SMSHub `{smshub_country_name_for_aws_dropdown}`: `{target_country_code_aws}`")

        for phone_otp_try in range(1, max_phone_otp_attempts + 1):
            check_stop_event()
            if last_sms_id:
                try:
                    cancel_url = f"http://smshub.org/stubs/handler_api.php?api_key={data['smshub_api_key']}&action=setStatus&status=8&id={last_sms_id}"
                    requests.get(cancel_url, timeout=5)
                    send_log(chat_id, f"🔄 *SMSHub*: Nomor `{last_sms_id}` dibatalkan (jika sebelumnya digunakan).")
                except Exception as e_cancel:
                    send_log(chat_id, f"⚠️ *SMSHub Cancel*: ERROR: `{e_cancel}`")

            smshub_api_key = data.get('smshub_api_key')
            smshub_country_id = data.get('smshub_country')
            smshub_operator_name = data.get('smshub_operator') # This is the operator name stored in settings
            smshub_max_price = data.get('smshub_max_price')

            if not smshub_api_key or not smshub_country_id or not smshub_operator_name or smshub_max_price is None:
                send_log(chat_id, "❌ *Signup Gagal*: Pengaturan SMSHub (API Key, Country, Operator, atau Max Price) belum lengkap.", is_error=True)
                driver.quit()
                return

            id_sms, nomor_sms_raw = get_smshub_number_robust(smshub_api_key, smshub_country_id, smshub_operator_name, smshub_max_price, chat_id)
            
            if not id_sms or not nomor_sms_raw:
                send_log(chat_id, "⚠️ *SMSHub*: Gagal ambil nomor untuk verifikasi. Mencoba lagi jika ada sisa attempt.")
                if phone_otp_try == max_phone_otp_attempts:
                    send_log(chat_id, "❌ *Signup Gagal*: Gagal total ambil nomor setelah semua percobaan.", is_error=True)
                    driver.quit()
                    return
                time.sleep(10)
                continue

            last_sms_id = id_sms
            nomor_sms_for_input = nomor_sms_raw
            if target_country_code_aws and nomor_sms_raw.startswith(target_country_code_aws.replace('+', '')):
                # Remove o código do país do início do número
                nomor_sms_for_input = nomor_sms_raw[len(target_country_code_aws.replace('+', '')):]
                send_log(chat_id, f"✅ *Phone OTP*: Código do país removido. Número para inserir na AWS: `{nomor_sms_for_input}`")
            # A cláusula 'else' que enviava a mensagem foi removida.
            # O bot usará o número completo se o código do país não corresponder, sem enviar uma mensagem de log.


            try:
                phone_country_dropdown_verif = wait.until(EC.element_to_be_clickable((By.XPATH, '//*[@id="awsui-select-0"]/div/awsui-icon/span')))
                click_with_mouse(driver, phone_country_dropdown_verif)
                random_sleep(0.8, 1.5)
                
                # --- Otimização: Pular a busca e clicar diretamente na opção ---
                phone_country_option_found_sms = False
                send_log(chat_id, "ℹ️ Phone OTP: Tentando clicar diretamente na opção do país na lista...")

                # Locators for SMS phone code dropdown options
                phone_code_options_locators_sms = [
                    (By.XPATH, f"//span[normalize-space(text())='{smshub_country_name_for_aws_dropdown}']"),
                    (By.XPATH, f"//span[contains(normalize-space(text()),'{smshub_country_name_for_aws_dropdown.split()[0]}')]" if smshub_country_name_for_aws_dropdown else ""), # Handle empty split
                    (By.XPATH, f"//span[contains(normalize-space(text()),'{target_country_code_aws}')]"),
                    (By.XPATH, f"//span[contains(normalize-space(text()),'United States') or contains(normalize-space(text()),'USA')]"),
                    (By.XPATH, f"//span[contains(normalize-space(text()),'United Kingdom') or contains(normalize-space(text()),'UK')]")
                ]
                # Filter out empty locators if split() resulted in empty string
                phone_code_options_locators_sms = [loc for loc in phone_code_options_locators_sms if loc[1]]

                for locator in phone_code_options_locators_sms: 
                    try:
                        # Usar um tempo de espera curto aqui, pois a lista já deve estar visível
                        country_option_verif = WebDriverWait(driver, 5).until(EC.element_to_be_clickable(locator))
                        click_with_mouse(driver, country_option_verif)
                        phone_country_option_found_sms = True
                        send_log(chat_id, f"✅ Phone OTP: Código do país '{smshub_country_name_for_aws_dropdown}' ({target_country_code_aws}) selecionado com sucesso.")
                        break # Sai do loop se for bem-sucedido
                    except TimeoutException:
                        pass # Tenta o próximo localizador
                    except Exception as e:
                        send_log(chat_id, f"⚠️ Phone OTP: Falha ao selecionar o código do país '{smshub_country_name_for_aws_dropdown}' com o localizador `{locator[1]}`: `{e}`. Tentando o próximo.")
                        pass
                
                if not phone_country_option_found_sms:
                    send_log(chat_id, f"❌ Phone OTP: O código do país para '{smshub_country_name_for_aws_dropdown}' não foi encontrado na lista suspensa da AWS. O processo foi interrompido.", is_error=True)
                    save_screenshot(driver, user_dir, "phone_country_selection_failed_sms_page")
                    driver.quit()
                    return
                # --- Fim da Otimização ---

                phone_input_verif_el = wait.until(EC.element_to_be_clickable((By.XPATH, '//*[@id="awsui-input-1"]')))
                input_with_delay(phone_input_verif_el, nomor_sms_for_input)
                send_log(chat_id, f"✅ *Phone OTP*: Nomor telepon `{nomor_sms_for_input}` diinputkan.")
                random_sleep(0.8, 1.5)
                human_like_interaction(driver)
                random_sleep(1, 2)
                
                send_sms_button = driver.find_element(By.XPATH, '//*[@id="IdentityVerification"]/fieldset/awsui-button/button/span')
                click_with_mouse(driver, send_sms_button)
                
                # --- Panggil fungsi solve_captcha_helper di sini untuk CAPTCHA SMS ---
                captcha_solved_on_phone_page = solve_captcha_helper(driver, wait, chat_id, user_dir, data['anti_captcha_api_key'], "CAPTCHA Phone (after Send SMS)")

                if not captcha_solved_on_phone_page:
                    send_log(chat_id, "❌ *Signup Gagal*: Gagal mengatasi CAPTCHA di halaman verifikasi telepon.", is_error=True)
                    driver.quit()
                    return

                # Wait for OTP input field AFTER potential CAPTCHA solve
                try:
                    WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.ID, "awsui-input-2")))
                    send_log(chat_id, "✅ *Navigasi*: Input field OTP terdeteksi. Melanjutkan.")
                except TimeoutException:
                    send_log(chat_id, "❌ *Navigasi*: Timeout! OTP field tidak muncul setelah Send SMS/CAPTCHA. Gagal.", is_error=True)
                    save_screenshot(driver, user_dir, f"phone_send_sms_stuck_try_{phone_otp_try}")
                    if phone_otp_try == max_phone_otp_attempts:
                        driver.quit()
                        return
                    driver.refresh(); random_sleep(3,5)
                    continue
                
            except Exception as e:
                send_log(chat_id, f"❌ *Phone Verif Input*: ERROR: `{e}`", is_error=True)
                save_screenshot(driver, user_dir, f"phone_verif_error_try_{phone_otp_try}")
                if phone_otp_try == max_phone_otp_attempts:
                    driver.quit()
                    return
                try: driver.refresh(); random_sleep(3,5)
                except: pass
                continue

            send_log(chat_id, f"⏳ *OTP SMSHub*: Menunggu OTP SMS dari SMSHub (ID: `{id_sms}`)...")
            otp_sms_code = get_sms_otp(id_sms, data['smshub_api_key'], chat_id, max_wait=120)
            
            if otp_sms_code:
                try:
                    otp_input_el = wait.until(EC.presence_of_element_located((By.ID, "awsui-input-2")))
                    input_with_delay(otp_input_el, otp_sms_code)
                    random_sleep(0.8,1.5)
                    
                    continue_button_locator = (By.XPATH, "//span[contains(text(), 'Continue (step 4 of 5)')]")
                    verify_code_button = wait.until(EC.element_to_be_clickable(continue_button_locator))
                    click_with_mouse(driver, verify_code_button)
                    
                    # Wait for support plan page or incorrect OTP message
                    try:
                        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "#SupportPlan")))
                        phone_otp_success = True
                        send_log(chat_id, "✅ *OTP SMSHub*: OTP SMS berhasil diverifikasi!")
                        break
                    except TimeoutException:
                        incorrect_otp_msg = driver.find_elements(By.XPATH, "//*[contains(text(), 'Incorrect verification code') or contains(text(), 'code is not valid')]")
                        if any(el.is_displayed() for el in incorrect_otp_msg):
                            send_log(chat_id, "⚠️ *OTP SMSHub*: Kode verifikasi salah. Mencoba nomor baru...")
                            save_screenshot(driver, user_dir, f"incorrect_sms_otp_try_{phone_otp_try}")
                        else:
                            send_log(chat_id, "⚠️ *OTP SMSHub*: Tidak ada pesan error OTP tapi tidak maju ke halaman Support Plan. Mengulang...", is_error=True)
                            save_log(chat_id, f"DEBUG: Current URL after SMS OTP submit (stuck): {driver.current_url}")
                            save_screenshot(driver, user_dir, f"sms_otp_stuck_try_{phone_otp_try}")
                            driver.refresh(); random_sleep(3,5)
                            continue # Continue to next attempt
                except Exception as e_otp_input:
                    send_log(chat_id, f"❌ *OTP SMS Input*: ERROR: `{e_otp_input}`", is_error=True)
                    save_screenshot(driver, user_dir, f"sms_otp_input_error_try_{phone_otp_try}")
            else:
                send_log(chat_id, "⚠️ *OTP SMSHub*: Tidak menerima OTP dalam 2 menit. Mencoba nomor baru...")

        if not phone_otp_success:
            send_log(chat_id, "❌ *Signup Gagal*: Gagal verifikasi telepon setelah semua percobaan.", is_error=True)
            save_screenshot(driver, user_dir, "phone_otp_total_failure")
            driver.quit()
            return

        # --- 7. Step: Choose Support Plan ---
        send_log(chat_id, "--- *Langkah 7*: Pilih Support Plan ---")
        try:
            check_stop_event()
            support_plan_btn = WebDriverWait(driver, 20).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "#SupportPlan > fieldset > div.CenteredButton_centeredButtonContainer_hSCKu > awsui-button > button > span"))
            )
            click_with_mouse(driver, support_plan_btn)
            send_log(chat_id, "✅ *Support Plan*: Basic Support - Free dipilih. Menyelesaikan pendaftaran...")
            
            # Wait for final confirmation or console page
            WebDriverWait(driver, 45).until( # Increased wait for final page load
                EC.any_of(
                    EC.url_contains("console.aws.amazon.com"),
                    EC.presence_of_element_located((By.XPATH, "//*[contains(text(), 'Congratulations') or contains(text(), 'Welcome to Amazon Web Services')]"))
                )
            )

        except Exception as e:
            send_log(chat_id, f"❌ *Support Plan*: Tidak dapat memilih Basic Support atau menyelesaikan pendaftaran: `{e}`", is_error=True)
            save_screenshot(driver, user_dir, "support_plan_error")
            driver.quit()
            return

        # --- Check Final Confirmation Page ---
        send_log(chat_id, "🔍 *Pengecekan*: Memeriksa halaman konfirmasi akhir...")
        final_screenshot_path = None
        try:
            # If we reached here, it means the WebDriverWait above passed
            send_log(chat_id, "🎉 *AKUN AWS SUKSES DIDAFTAR!* 🎉")
            final_screenshot_path = save_screenshot(driver, user_dir, "signup_success_final_page")
            
            send_log(chat_id, "🥳🥳🥳 *Selamat! Akun AWS Anda berhasil dibuat!* 🥳🥳🥳\n\n"
                                     "Silakan cek email Anda untuk informasi login. "
                                     "Screenshot halaman terakhir terlampir.",
                                     parse_mode='Markdown', photo_path=final_screenshot_path)

        except Exception as e:
            send_log(chat_id, f"⚠️ *Verifikasi Akhir*: Tidak dapat mengkonfirmasi halaman sukses akhir, namun proses mungkin berhasil. Periksa email Anda. Error: `{e}`", is_error=True)
            final_screenshot_path = save_screenshot(driver, user_dir, "signup_uncertain_final_page")
            send_log(chat_id, "⚠️ *Akun mungkin berhasil dibuat, namun tidak dapat dikonfirmasi!* ⚠️\n\n"
                                     "Terjadi masalah saat memverifikasi halaman akhir. "
                                     "Mohon *segera cek email* Anda untuk informasi login dan verifikasi akun AWS. "
                                     "Screenshot halaman terakhir terlampir (jika ada).",
                                     parse_mode='Markdown', photo_path=final_screenshot_path)


        # --- Save Successfully Created Account Data ---
        success_data = f"""
== AWS Account Created ==
Timestamp: {time.strftime("%Y-%m-%d %H:%M:%S")}
Email: {email}
AWS Account Name: {aws_account_name}
Full Name (Contact/Billing): {full_name}
Root Password: {data['root_password']}
"""
        success_file_path = os.path.join(user_dir, "success_accounts.txt")
        with open(success_file_path, "a", encoding="utf-8") as f:
            f.write(success_data)
            f.write("\n" + "="*50 + "\n\n")
        send_log(chat_id, f"📄 *INFO*: Data akun berhasil disimpan ke `{success_file_path}`")

        if os.path.exists(success_file_path):
            try:
                bot.send_document(chat_id, open(success_file_path, "rb"), caption="🎉 *AKUN AWS BERHASIL DIBUAT!* 🎉\n\nBerikut detail akun Anda.")
            except Exception as e:
                send_log(chat_id, f"❌ *File*: Gagal mengirim dokumen `{success_file_path}`: {e}", is_error=True)
        else:
            send_log(chat_id, f"❌ *File*: `{success_file_path}` tidak ditemukan untuk dikirim.", is_error=True)

    except KeyboardInterrupt:
        send_log(chat_id, "🛑 *Proses dihentikan oleh pengguna.*")
    except Exception as e_global:
        send_log(chat_id, f"❌ *ERROR GLOBAL*: Proses AWS Signup gagal dengan error tak terduga: `{e_global}`", is_error=True)
        if driver:
            save_screenshot(driver, user_dir, "global_process_error")
    finally:
        if driver:
            driver.quit()
        # Bersihkan event setelah proses selesai atau dihentikan
        if chat_id in process_events:
            del process_events[chat_id]
        send_log(chat_id, "🏁 *Proses Selesai*: Proses AWS Signup Selesai (atau dihentikan).")


# =============== TELEGRAM BOT HANDLERS =================

def menu_utama_markup():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    # Baris 1: Mulai Signup AWS
    markup.add(types.KeyboardButton('🚀 Mulai Signup AWS'))
    # Baris 2: Pengaturan Akun, Pengaturan Pembayaran
    markup.add(types.KeyboardButton('⚙️ Pengaturan Akun'), types.KeyboardButton('💳 Pengaturan Pembayaran'))
    # Baris 3: Pengaturan SMSHub, Pengaturan Proxy
    markup.add(types.KeyboardButton('📞 Pengaturan SMSHub'), types.KeyboardButton('🔌 Pengaturan Proxy'))
    # Baris 4: Tampilkan Pengaturan
    markup.add(types.KeyboardButton('📋 Tampilkan Pengaturan'))
    return markup

def stop_process_markup():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.add(types.KeyboardButton('🛑 Stop Proses'))
    return markup

def settings_account_markup(message):
    """Dynamically generates the account settings menu based on email_mode."""
    settings = load_user_settings(message)
    email_mode = settings.get('email_mode', 'Random')

    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.add(types.KeyboardButton(f'📧 Set Mode Email ({email_mode})'))
    
    if email_mode == 'Random':
        markup.add(types.KeyboardButton('✉️ Set Gmail Akun (Otomatis)'))
        markup.add(types.KeyboardButton('🌐 Set Domain Email (Otomatis)'))
    
    markup.add(types.KeyboardButton('🔑 Set Anti-Captcha API Key'))
    markup.add(types.KeyboardButton('🔒 Set Root Password AWS'))
    markup.add(types.KeyboardButton('🌍 Set Negara Akun'))
    markup.add(types.KeyboardButton('🔙 Kembali ke Menu Utama'))
    return markup


def settings_payment_markup():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.add(types.KeyboardButton('💳 Set Nomor Kartu Kredit'))
    markup.add(types.KeyboardButton('📅 Set Bulan Kedaluwarsa'))
    markup.add(types.KeyboardButton('🗓️ Set Tahun Kedaluwarsa'))
    markup.add(types.KeyboardButton('🔢 Set CVV Kartu'))
    markup.add(types.KeyboardButton('🔙 Kembali ke Menu Utama'))
    return markup

def settings_smshub_markup():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.add(types.KeyboardButton('🔑 Set SMSHub API Key'))
    markup.add(types.KeyboardButton('📍 Set SMSHub Negara & Operator'))
    markup.add(types.KeyboardButton('💰 Set SMSHub Harga Maksimal'))
    markup.add(types.KeyboardButton('🔙 Kembali ke Menu Utama'))
    return markup

def settings_proxy_markup(current_status="Nonaktif"):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.add(types.KeyboardButton(f'Proxy Saat Ini: {current_status}'))
    markup.add(types.KeyboardButton('✅ Aktifkan Proxy'), types.KeyboardButton('❌ Nonaktifkan Proxy'))
    markup.add(types.KeyboardButton('⚙️ Atur Detail Proxy'))
    markup.add(types.KeyboardButton('🔙 Kembali ke Menu Utama'))
    return markup

def batal_markup():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.add(types.KeyboardButton('Batal'))
    return markup

def validate_with_gemini(user_input: str, input_type: str, chat_id: int):
    """
    Memvalidasi input pengguna menggunakan API dan menyarankan perbaikan.
    """
    send_log(chat_id, f"🤖 *Wanbot Validator*: Memvalidasi input '{user_input}' sebagai '{input_type}'...")
    
    prompt = (
        f"Analyze the user's input to see if it's a valid '{input_type}'. "
        f"The user's input is: '{user_input}'. "
        f"If the input is a common typo or a slight variation of a valid entry, please correct it. "
        f"For example, if the input_type is 'full country name' and the user input is 'Indonesa', the suggestion should be 'Indonesia'. "
        f"If the input is already perfectly valid, the suggestion should be the same as the user input. "
        f"If the input is complete nonsense and cannot be corrected (e.g., 'asdfg' for a country name), the suggestion should be null. "
        f"Respond ONLY with a single JSON object with these exact keys: "
        f"`is_valid` (boolean), `suggestion` (string or null), `reason` (string, e.g., 'Correct' or 'Typo corrected')."
    )
    
    try:
        response = gemini_model.generate_content(prompt)
        raw_text = response.text.strip()
        
        json_match = re.search(r"\{.*\}", raw_text, re.DOTALL)
        if json_match:
            json_str = json_match.group(0)
            data = json.loads(json_str)
            send_log(chat_id, f"🤖 *Wanbot Validator*: Hasil: `{json.dumps(data)}`") # Escape JSON for Telegram
            return data
        else:
            send_log(chat_id, f"⚠️ *Wanbot Validator*: Gagal mengekstrak JSON dari respon. Fallback ke validasi manual.")
            return {'is_valid': True, 'suggestion': user_input, 'reason': 'API validation failed'}
            
    except Exception as e:
        send_log(chat_id, f"❌ *Wanbot Validator*: Error saat memanggil API: `{e}`. Fallback ke validasi manual.", is_error=True)
        return {'is_valid': True, 'suggestion': user_input, 'reason': 'API validation failed'}

# --- NEW FUNCTION: Parse the country-and-operators.txt file ---
def parse_smshub_data(file_path):
    """
    Parses the country-and-operators.txt file into a dictionary.
    Format:
    {
        "id_str": {
            "name": "Country Name",
            "operators": ["op1", "op2", ...],
            "original_country_name": "OriginalName" # For fuzzy matching
        },
        ...
    }
    """
    data = {}
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            # Skip header
            if lines and lines[0].strip().startswith("ID\tName"):
                lines = lines[1:]

            for line in lines:
                parts = line.strip().split('\t')
                if len(parts) >= 4:
                    country_id = parts[0]
                    name_raw = parts[1] # e.g., "Russia", "Southafrica"
                    operators_str = parts[3] # e.g., "aiva,any,aquafon"
                    
                    operators_list = [op.strip().lower() for op in operators_str.split(',') if op.strip()]
                    
                    data[country_id] = {
                        "name": name_raw.replace("_", " ").title(), # Convert "Southafrica" to "South Africa"
                        "operators": operators_list,
                        "original_country_name": name_raw.lower() # Store original for matching
                    }
    except FileNotFoundError:
        print(f"[ERROR] File '{file_path}' not found. SMSHub country/operator suggestions will be limited.")
    except Exception as e:
        print(f"[ERROR] Error parsing '{file_path}': {e}")
    return data

@bot.message_handler(commands=['start', 'menu'])
def start_handler(message):
    get_user_dir(message)
    bot.send_message(message.chat.id,
                     "👋 Selamat datang di *Bot AWS Signup*!\n\n"
                     "Saya akan membantu Anda mendaftar akun AWS secara otomatis. "
                     "Mohon lengkapi semua pengaturan yang diperlukan sebelum memulai proses signup.\n\n"
                     "Gunakan tombol di bawah untuk navigasi.",
                     parse_mode='Markdown',
                     reply_markup=menu_utama_markup())

@bot.message_handler(func=lambda message: message.text == '📋 Tampilkan Pengaturan')
def show_settings_handler(message):
    chat_id = message.chat.id
    settings = load_user_settings(message)
    if not settings:
        bot.send_message(chat_id, "ℹ️ Belum ada pengaturan yang disimpan.", reply_markup=menu_utama_markup())
        return

    settings_text = "✨ *Pengaturan Saat Ini:*\n\n"
    
    # --- [MODIFIED] Account Settings Display ---
    email_mode = settings.get('email_mode', 'Random')
    settings_text += f"⚙️ *Mode Email*: *{email_mode}*\n"
    if email_mode == 'Random':
        settings_text += f"- *Domain Email (Otomatis)*: `{settings.get('email_domain', '_Belum diatur_')}`\n"
        settings_text += f"- *Gmail Akun (Otomatis)*: `{settings.get('gmail_user', '_Belum diatur_')}`\n"
        settings_text += f"- *Gmail App Password (Otomatis)*: `{'*' * len(str(settings.get('gmail_pass')))}`\n" if settings.get('gmail_pass') else "- *Gmail App Password (Otomatis)*: `_Belum diatur_`\n"
    settings_text += f"- *Negara Akun AWS*: `{settings.get('country', '_Belum diatur_')}`\n"
    settings_text += f"- *Root Password AWS*: `{'*' * len(str(settings.get('root_password')))}`\n" if settings.get('root_password') else "- *Root Password AWS*: `_Belum diatur_`\n"
    settings_text += f"- *API Key Anti-Captcha*: `{'*' * len(str(settings.get('anti_captcha_api_key')))}`\n" if settings.get('anti_captcha_api_key') else "- *API Key Anti-Captcha*: `_Belum diatur_`\n"
    
    # --- Payment Settings ---
    settings_text += "\n💳 *Pengaturan Pembayaran:*\n"
    settings_text += f"- *Nomor Kartu Kredit*: `{'*' * len(str(settings.get('credit_card')))}`\n" if settings.get('credit_card') else "- *Nomor Kartu Kredit*: `_Belum diatur_`\n"
    settings_text += f"- *Bulan Kedaluwarsa*: `{settings.get('month', '_Belum diatur_')}`\n"
    settings_text += f"- *Tahun Kedaluwarsa*: `{settings.get('year', '_Belum diatur_')}`\n"
    settings_text += f"- *CVV Kartu*: `{'*' * len(str(settings.get('cvv')))}`\n" if settings.get('cvv') else "- *CVV Kartu*: `_Belum diatur_`\n"
    
    # --- SMSHub Settings ---
    settings_text += "\n📞 *Pengaturan SMSHub:*\n"
    settings_text += f"- *SMSHub API Key*: `{'*' * len(str(settings.get('smshub_api_key')))}`\n" if settings.get('smshub_api_key') else "- *SMSHub API Key*: `_Belum diatur_`\n"
    smshub_country_display = f"ID `{settings.get('smshub_country', '_Belum diatur_')}` (Nama: *{settings.get('smshub_country_name', '_Belum diatur_')}*)"
    settings_text += f"- *SMSHub Negara*: {smshub_country_display}\n"
    settings_text += f"- *SMSHub Operator*: `{settings.get('smshub_operator', '_Belum diatur_')}`\n"
    settings_text += f"- *SMSHub Harga Maksimal*: `${settings.get('smshub_max_price', '_Belum diatur_')}`\n"

    # --- Proxy Settings ---
    settings_text += "\n🔌 *Pengaturan Proxy:*\n"
    proxy_status_display = "Aktif" if settings.get('use_proxy', False) else "Nonaktif"
    settings_text += f"- *Status Proxy*: *{proxy_status_display}*\n"
    if settings.get('proxy_string'):
        proxy_parts = settings['proxy_string'].split(':')
        if len(proxy_parts) >= 2:
            display_proxy_detail = f"`{proxy_parts[0]}:{proxy_parts[1]}:***:***`"
        else:
            display_proxy_detail = "`Format tidak valid`"
        settings_text += f"- *Detail Proxy*: {display_proxy_detail}\n"
    else:
        settings_text += "- *Detail Proxy*: `_Belum diatur_`\n"

    bot.send_message(chat_id, settings_text, parse_mode='Markdown', reply_markup=menu_utama_markup())


@bot.message_handler(func=lambda m: True)
def main_handler(message):
    chat_id = message.chat.id
    text = message.text.strip()

    # Cek jika ada input manual yang diharapkan
    if chat_id in manual_input_data:
        manual_input_data[chat_id]['value'] = text
        manual_input_data[chat_id]['event'].set()
        return
        
    if text == '🛑 Stop Proses':
        if chat_id in process_events:
            process_events[chat_id].set()
            bot.send_message(chat_id, "🛑 *Permintaan untuk menghentikan proses diterima...*", reply_markup=menu_utama_markup())
        else:
            bot.send_message(chat_id, "ℹ️ Tidak ada proses yang sedang berjalan untuk dihentikan.", reply_markup=menu_utama_markup())
        return

    if text.lower() in ['batal', '🔙 kembali ke menu utama', '/cancel', '/back', '/menu']:
        bot.send_message(chat_id, "✅ Operasi dibatalkan. Kembali ke menu utama.", reply_markup=menu_utama_markup())
        return

    # --- Menu Navigation ---
    if text == '⚙️ Pengaturan Akun':
        bot.send_message(chat_id, "Pilih pengaturan akun yang ingin Anda atur:", reply_markup=settings_account_markup(message))
    elif text == '💳 Pengaturan Pembayaran':
        bot.send_message(chat_id, "Pilih pengaturan pembayaran yang ingin Anda atur:", reply_markup=settings_payment_markup())
    elif text == '📞 Pengaturan SMSHub':
        bot.send_message(chat_id, "Pilih pengaturan SMSHub yang ingin Anda atur:", reply_markup=settings_smshub_markup())
    elif text == '🔌 Pengaturan Proxy':
        settings = load_user_settings(message)
        proxy_status = "Aktif" if settings.get('use_proxy', False) and settings.get('proxy_string') else "Nonaktif"
        bot.send_message(chat_id, f"Pilih pengaturan proxy yang ingin Anda atur. Status saat ini: *{proxy_status}*", parse_mode='Markdown', reply_markup=settings_proxy_markup(proxy_status))
    
    # --- Account Settings ---
    elif text.startswith('📧 Set Mode Email'):
        msg = bot.send_message(chat_id, "Pilih mode penggunaan email untuk pendaftaran:", reply_markup=email_mode_choice_markup())
        bot.register_next_step_handler(msg, handle_email_mode_selection)
    elif text == '🔑 Set Anti-Captcha API Key':
        msg = bot.send_message(chat_id, "Masukkan *API Key Anti-Captcha* Anda:", parse_mode='Markdown', reply_markup=batal_markup())
        bot.register_next_step_handler(msg, set_anti_captcha)
    elif text == '✉️ Set Gmail Akun (Otomatis)':
        msg = bot.send_message(chat_id, "Masukkan alamat email *GMAIL* Anda (untuk ambil OTP AWS secara otomatis):", parse_mode='Markdown', reply_markup=batal_markup())
        bot.register_next_step_handler(msg, set_gmail_user)
    elif text == '🔒 Set Root Password AWS':
        msg = bot.send_message(chat_id, "Masukkan *Root Password* untuk akun AWS baru (minimal 8 karakter, kombinasi huruf besar/kecil, angka, simbol):", parse_mode='Markdown', reply_markup=batal_markup())
        bot.register_next_step_handler(msg, set_root_password)
    elif text == '🌍 Set Negara Akun':
        msg = bot.send_message(chat_id, "Masukkan nama *Negara* (Nama lengkap, contoh: `Indonesia`, `United States`):", parse_mode='Markdown', reply_markup=batal_markup())
        bot.register_next_step_handler(msg, set_country)
    elif text == '🌐 Set Domain Email (Otomatis)':
        msg = bot.send_message(chat_id, "Masukkan *domain email* yang akan digunakan untuk membuat akun AWS (contoh: `example.com`, `mydomain.pro`):", parse_mode='Markdown', reply_markup=batal_markup())
        bot.register_next_step_handler(msg, set_email_domain)
    
    # --- Proxy Settings ---
    elif text == '✅ Aktifkan Proxy':
        data = load_user_settings(message)
        if not data.get('proxy_string'):
            bot.send_message(chat_id, "⚠️ *Detail Proxy belum diatur!* Silakan atur detail proxy terlebih dahulu.", parse_mode='Markdown', reply_markup=settings_proxy_markup("Nonaktif"))
            return
        data['use_proxy'] = True
        save_user_settings(message, data)
        bot.send_message(chat_id, "✅ *Proxy diaktifkan*.", parse_mode='Markdown', reply_markup=settings_proxy_markup("Aktif"))
    elif text == '❌ Nonaktifkan Proxy':
        data = load_user_settings(message)
        data['use_proxy'] = False
        save_user_settings(message, data)
        bot.send_message(chat_id, "✅ *Proxy dinonaktifkan*.", parse_mode='Markdown', reply_markup=settings_proxy_markup("Nonaktif"))
    elif text == '⚙️ Atur Detail Proxy':
        msg = bot.send_message(
            chat_id, 
            "Masukkan *proxy* Anda dengan format:\n"
            "`IP:PORT` (tanpa autentikasi)\n"
            "atau\n"
            "`IP:PORT:USER:PASS` (dengan autentikasi)\n\n"
            "Ketik `hapus` untuk menghapus detail proxy yang tersimpan.",
            parse_mode='Markdown', 
            reply_markup=batal_markup()
        )
        bot.register_next_step_handler(msg, set_proxy_details)

    # --- Payment Settings ---
    elif text == '💳 Set Nomor Kartu Kredit':
        msg = bot.send_message(chat_id, "Masukkan *Nomor Kartu Kredit/Debit* Anda (hanya angka, tanpa spasi):", parse_mode='Markdown', reply_markup=batal_markup())
        bot.register_next_step_handler(msg, set_credit_card)
    elif text == '📅 Set Bulan Kedaluwarsa':
        msg = bot.send_message(chat_id, "Masukkan *Bulan Kedaluwarsa Kartu* (Nama lengkap, contoh: `January`, `December`):", parse_mode='Markdown', reply_markup=batal_markup())
        bot.register_next_step_handler(msg, set_month)
    elif text == '🗓️ Set Tahun Kedaluwarsa':
        msg = bot.send_message(chat_id, "Masukkan *Tahun Kedaluwarsa Kartu* (Format YYYY, contoh: `2025`):", parse_mode='Markdown', reply_markup=batal_markup())
        bot.register_next_step_handler(msg, set_year)
    elif text == '🔢 Set CVV Kartu':
        msg = bot.send_message(chat_id, "Masukkan *CVV Kartu* (3 atau 4 digit, atau ketik `0`/`kosong` jika tidak ada):", parse_mode='Markdown', reply_markup=batal_markup())
        bot.register_next_step_handler(msg, set_cvv)
    
    # --- SMSHub Settings ---
    elif text == '🔑 Set SMSHub API Key':
        msg = bot.send_message(chat_id, "Masukkan *API Key SMSHub* Anda:", parse_mode='Markdown', reply_markup=batal_markup())
        bot.register_next_step_handler(msg, set_smshub_api_key)
    elif text == '📍 Set SMSHub Negara & Operator':
        msg = bot.send_message(chat_id, 
            "Masukkan *ID Numerik Negara* untuk SMSHub (contoh: `6` untuk Indonesia, `1` untuk USA).\n"
            "Anda juga bisa mengetik *nama negara* (contoh: `Indonesia`, `United States`).\n"
            "Daftar negara dan ID bisa dilihat di [sini](https://smshub.org/prices/get/en).\n\n"
            "Ketik `Batal` untuk membatalkan.",
            parse_mode='Markdown', 
            reply_markup=batal_markup(), 
            disable_web_page_preview=True)
        bot.register_next_step_handler(msg, set_smshub_country_id_input)
    elif text == '💰 Set SMSHub Harga Maksimal':
        msg = bot.send_message(chat_id, "Masukkan *Harga Maksimal* untuk nomor SMSHub (contoh: `1.5` untuk $1.50):", parse_mode='Markdown', reply_markup=batal_markup())
        bot.register_next_step_handler(msg, set_smshub_max_price)
    
    # --- Start Process ---
    elif text == '🚀 Mulai Signup AWS':
        data = load_user_settings(message)
        email_mode = data.get('email_mode', 'Random')
        
        # [MODIFIED] Dynamic check for required keys
        required_keys_base = {
            'anti_captcha_api_key': "API Key Anti-Captcha",
            'smshub_api_key': "API Key SMSHub",
            'credit_card': "Nomor Kartu Kredit",
            'month': "Bulan Kedaluwarsa Kartu",
            'year': "Tahun Kedaluwarsa Kartu",
            'root_password': "Root Password AWS",
            'country': "Negara Akun",
            'smshub_country': "SMSHub Country ID",
            'smshub_country_name': "SMSHub Country Name",
            'smshub_operator': "SMSHub Operator",
            'smshub_max_price': "SMSHub Max Price"
        }

        if email_mode == 'Random':
            required_keys_base.update({
                'gmail_user': "Email Gmail (Otomatis)",
                'gmail_pass': "Password Gmail (Otomatis)",
                'email_domain': "Domain Email (Otomatis)"
            })
        
        missing_display_names = [name for key, name in required_keys_base.items() if not data.get(key) and data.get(key) != 0]

        if data.get('use_proxy', False) and not data.get('proxy_string'):
            missing_display_names.append("Detail Proxy (diaktifkan tapi kosong)")

        if missing_display_names:
            missing_items_str = "\n- ".join(missing_display_names)
            bot.send_message(
                chat_id,
                f"⚠️ *Data Belum Lengkap!* ⚠️\n\n"
                f"Data berikut belum diatur atau kosong untuk mode *{email_mode}*:\n- {missing_items_str}\n\n"
                f"Silakan lengkapi semua data ini sebelum memulai proses signup.",
                parse_mode='Markdown',
                reply_markup=menu_utama_markup()
            )
            return

        if not data.get('cvv'):
            bot.send_message(chat_id, "ℹ️ *Info*: CVV tidak di-set. Akan digunakan nilai default '000' jika diperlukan saat proses signup.", parse_mode='Markdown')

        confirmation_text = "Apakah Anda yakin ingin memulai proses AWS Signup dengan pengaturan saat ini? Pastikan semua data sudah benar."
        markup_confirm = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        markup_confirm.add(types.KeyboardButton('✅ YA, Mulai Sekarang!'), types.KeyboardButton('❌ TIDAK, Kembali'))
        msg = bot.send_message(chat_id, confirmation_text, parse_mode='Markdown', reply_markup=markup_confirm)
        bot.register_next_step_handler(msg, confirm_start_signup)
    else:
        bot.send_message(chat_id, "🤔 Perintah tidak dikenali. Silakan gunakan tombol menu yang tersedia.", reply_markup=menu_utama_markup())

def confirm_start_signup(message):
    chat_id = message.chat.id
    if message.text == '✅ I have completed 3DS verification (redirected)':
        # This branch handles the manual 3DS confirmation, not the start signup
        # It needs to be handled by the manual_input_data mechanism.
        # This part of the code should not be reached if manual_input_data is properly set.
        # However, to prevent a crash if somehow it is, we'll log it.
        send_log(chat_id, "WARNING: Unexpected 'I have completed 3DS verification' message in confirm_start_signup handler.")
        # Attempt to trigger the manual input event if it's waiting
        if chat_id in manual_input_data and 'event' in manual_input_data[chat_id]:
            manual_input_data[chat_id]['value'] = message.text
            manual_input_data[chat_id]['event'].set()
        else:
            bot.send_message(chat_id, "✅ Operasi tidak dikenal, kembali ke menu utama.", reply_markup=menu_utama_markup())
        return
    elif message.text == '❌ 3DS failed / Cancel':
        send_log(chat_id, "WARNING: Unexpected '3DS failed / Cancel' message in confirm_start_signup handler.")
        if chat_id in manual_input_data and 'event' in manual_input_data[chat_id]:
            manual_input_data[chat_id]['value'] = message.text
            manual_input_data[chat_id]['event'].set()
        else:
            bot.send_message(chat_id, "✅ Operasi tidak dikenal, kembali ke menu utama.", reply_markup=menu_utama_markup())
        return
    elif message.text == '✅ YA, Mulai Sekarang!':
        
        bot.send_message(chat_id, "🚀 *Memulai Proses AWS Signup!* 🚀\n\n"
                                 "Proses ini mungkin memakan waktu beberapa menit. "
                                 "Mohon tunggu dengan sabar. Gunakan tombol di bawah untuk menghentikan proses kapan saja.",
                                 parse_mode='Markdown',
                                 reply_markup=stop_process_markup())
        
        threading.Thread(target=aws_signup_process, args=(message,)).start()
    else:
        bot.send_message(chat_id, "✅ Signup dibatalkan. Kembali ke menu utama.", reply_markup=menu_utama_markup())
                                                                                                        
def handle_batal_or_empty(message, next_handler_func, empty_err_msg="Input tidak boleh kosong."):
    chat_id = message.chat.id
    if message.text.strip().lower() == 'batal':
        bot.send_message(chat_id, "✅ Pengaturan dibatalkan. Kembali ke menu utama.", reply_markup=menu_utama_markup())
        return True
    if not message.text.strip():
        bot.send_message(chat_id, f"⚠️ {empty_err_msg} Coba lagi atau Batal.", parse_mode='Markdown', reply_markup=batal_markup())
        bot.register_next_step_handler(message, next_handler_func)
        return True
    return False

# --- [NEW] Email Mode Handlers ---
def email_mode_choice_markup():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.add(types.KeyboardButton('Gunakan Email Random (Otomatis)'))
    markup.add(types.KeyboardButton('Gunakan Email Manual'))
    markup.add(types.KeyboardButton('Batal'))
    return markup

def handle_email_mode_selection(message):
    chat_id = message.chat.id
    text = message.text.strip()
    data = load_user_settings(message)

    if text == 'Gunakan Email Random (Otomatis)':
        data['email_mode'] = 'Random'
        save_user_settings(message, data)
        bot.send_message(chat_id, "✅ Mode email diatur ke *Random (Otomatis)*. Pastikan Anda telah mengatur 'Gmail Akun' dan 'Domain Email'.", parse_mode='Markdown', reply_markup=settings_account_markup(message))
    elif text == 'Gunakan Email Manual':
        data['email_mode'] = 'Manual'
        # Hapus pengaturan yang tidak relevan untuk menghindari kebingungan
        if 'gmail_user' in data: del data['gmail_user']
        if 'gmail_pass' in data: del data['gmail_pass']
        if 'email_domain' in data: del data['email_domain']
        save_user_settings(message, data)
        bot.send_message(chat_id, "✅ Mode email diatur ke *Manual*. Bot akan meminta email dan OTP Anda saat proses signup.", parse_mode='Markdown', reply_markup=settings_account_markup(message))
    else:
        bot.send_message(chat_id, "✅ Pengaturan dibatalkan.", reply_markup=settings_account_markup(message))

# --- Existing Handlers (Modified slightly for new menu) ---

def set_anti_captcha(message):
    chat_id = message.chat.id
    if handle_batal_or_empty(message, set_anti_captcha, "API Key Anti-Captcha tidak boleh kosong."): return
    data = load_user_settings(message)
    data['anti_captcha_api_key'] = message.text.strip()
    save_user_settings(message, data)
    bot.send_message(chat_id, "✅ *API Key Anti-Captcha disimpan*.", parse_mode='Markdown', reply_markup=settings_account_markup(message))

def set_smshub_api_key(message):
    chat_id = message.chat.id
    if handle_batal_or_empty(message, set_smshub_api_key, "API Key SMSHub tidak boleh kosong."): return
    data = load_user_settings(message)
    data['smshub_api_key'] = message.text.strip()
    save_user_settings(message, data)
    bot.send_message(chat_id, "✅ *API Key SMSHub berhasil disimpan*.", parse_mode='Markdown', reply_markup=settings_smshub_markup())

def set_gmail_user(message):
    chat_id = message.chat.id
    if handle_batal_or_empty(message, set_gmail_user, "Email Gmail tidak boleh kosong."): return
    value = message.text.strip()
    if '@' not in value or '.' not in value.split('@')[-1]:
        bot.send_message(chat_id, "⚠️ Format email Gmail tidak valid. Coba lagi atau Batal.", parse_mode='Markdown', reply_markup=batal_markup())
        bot.register_next_step_handler(message, set_gmail_user)
        return
    data = load_user_settings(message)
    data['gmail_user'] = value
    save_user_settings(message, data)
    msg = bot.send_message(chat_id, "✅ *Email Gmail disimpan*.\n\nSekarang masukkan *Password Aplikasi Gmail* Anda (‼️ *PENTING*: Ini adalah Password Aplikasi, BUKAN password utama akun Google Anda!):", parse_mode='Markdown', reply_markup=batal_markup())
    bot.register_next_step_handler(msg, set_gmail_pass)

def set_gmail_pass(message):
    chat_id = message.chat.id
    if handle_batal_or_empty(message, set_gmail_pass, "Password Gmail tidak boleh kosong."): return
    data = load_user_settings(message)
    data['gmail_pass'] = message.text.strip()
    save_user_settings(message, data)
    bot.send_message(chat_id, "✅ *Email & Password Gmail berhasil disimpan*.", parse_mode='Markdown', reply_markup=settings_account_markup(message))

def set_credit_card(message):
    chat_id = message.chat.id
    if handle_batal_or_empty(message, set_credit_card, "Nomor Kartu Kredit tidak boleh kosong."): return
    value = message.text.strip().replace(" ","")
    if not value.isdigit() or not (13 <= len(value) <= 19):
        bot.send_message(chat_id, "⚠️ Nomor Kartu Kredit tidak valid (harus 13-19 digit angka). Coba lagi atau Batal.", parse_mode='Markdown', reply_markup=batal_markup())
        bot.register_next_step_handler(message, set_credit_card)
        return
    data = load_user_settings(message)
    data['credit_card'] = value
    save_user_settings(message, data)
    bot.send_message(chat_id, "✅ *Nomor Kartu Kredit disimpan*.\n\nPastikan Anda juga mengatur Bulan, Tahun Kedaluwarsa, dan CVV dari menu *Pengaturan Pembayaran*.", parse_mode='Markdown', reply_markup=settings_payment_markup())

def set_root_password(message):
    chat_id = message.chat.id
    if handle_batal_or_empty(message, set_root_password, "Root Password tidak boleh kosong."): return
    value = message.text.strip()
    if len(value) < 8:
        bot.send_message(chat_id, "⚠️ Root Password minimal 8 karakter. Coba lagi atau Batal.", parse_mode='Markdown', reply_markup=batal_markup())
        bot.register_next_step_handler(message, set_root_password)
        return
    data = load_user_settings(message)
    data['root_password'] = value
    save_user_settings(message, data)
    bot.send_message(chat_id, "✅ *Root Password disimpan*.", parse_mode='Markdown', reply_markup=settings_account_markup(message))

def set_cvv(message):
    chat_id = message.chat.id
    if message.text.strip().lower() == 'batal':
        bot.send_message(chat_id, "✅ Pengaturan CVV dibatalkan.", reply_markup=settings_payment_markup())
        return
    value = message.text.strip()
    data = load_user_settings(message)
    if not value or value == '0':
        data['cvv'] = ''
        save_user_settings(message, data)
        bot.send_message(chat_id, "✅ *CVV diatur untuk menggunakan default* ('000') jika tidak ada input.", parse_mode='Markdown', reply_markup=settings_payment_markup())
        return
    if not value.isdigit() or not (3 <= len(value) <= 4):
        bot.send_message(chat_id, "⚠️ CVV tidak valid (harus 3 atau 4 digit angka, atau `0`/`kosong` untuk default). Coba lagi atau Batal.", parse_mode='Markdown', reply_markup=batal_markup())
        bot.register_next_step_handler(message, set_cvv)
        return
    data['cvv'] = value
    save_user_settings(message, data)
    bot.send_message(chat_id, "✅ *CVV disimpan*.", parse_mode='Markdown', reply_markup=settings_payment_markup())

def set_month(message):
    chat_id = message.chat.id
    if handle_batal_or_empty(message, set_month, "Nama bulan tidak boleh kosong."): return
    
    value = message.text.strip()
    validation_result = validate_with_gemini(value, "month of the year (full English name)", chat_id)
    
    is_valid = validation_result.get('is_valid', False)
    suggestion = validation_result.get('suggestion')

    if is_valid and suggestion and value.lower() == suggestion.lower():
        data = load_user_settings(message)
        data['month'] = suggestion.title()
        save_user_settings(message, data)
        bot.send_message(chat_id, f"✅ *Bulan Kedaluwarsa disimpan*: `{suggestion.title()}`.", parse_mode='Markdown', reply_markup=settings_payment_markup())
    elif suggestion:
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        markup.add(types.KeyboardButton(f"Ya, gunakan '{suggestion}'"), types.KeyboardButton("Tidak, masukkan ulang"))
        markup.add(types.KeyboardButton("Batal"))
        msg = bot.send_message(chat_id, f"🤔 Maksud Anda *{suggestion}*? Mohon konfirmasi.", parse_mode='Markdown', reply_markup=markup)
        bot.register_next_step_handler(msg, lambda m: confirm_month_suggestion(m, message, suggestion))
    else:
        bot.send_message(chat_id, "⚠️ Nama bulan tidak valid. Masukkan nama bulan yang benar (e.g., `June`). Coba lagi atau Batal.", parse_mode='Markdown', reply_markup=batal_markup())
        bot.register_next_step_handler(message, set_month)

def confirm_month_suggestion(message, original_message, suggestion):
    chat_id = message.chat.id
    text = message.text.strip()

    if text.startswith("Ya, gunakan"):
        final_value = suggestion.title()
        data = load_user_settings(original_message)
        data['month'] = final_value
        save_user_settings(original_message, data)
        bot.send_message(chat_id, f"✅ *Bulan Kedaluwarsa disimpan*: `{final_value}`.", parse_mode='Markdown', reply_markup=settings_payment_markup())
    elif text == "Tidak, masukkan ulang":
        msg = bot.send_message(chat_id, "Baik, silakan masukkan ulang nama bulan:", reply_markup=batal_markup())
        bot.register_next_step_handler(msg, set_month)
    else:
        bot.send_message(chat_id, "✅ Pengaturan dibatalkan.", reply_markup=settings_payment_markup())

def set_year(message):
    chat_id = message.chat.id
    if handle_batal_or_empty(message, set_year, "Tahun kedaluwarsa tidak boleh kosong."): return
    value = message.text.strip()
    try:
        year_val = int(value)
        if not (len(value) == 4 and year_val >= time.localtime().tm_year):
            raise ValueError("Invalid year")
    except ValueError:
        bot.send_message(chat_id, "⚠️ Tahun Kedaluwarsa tidak valid (Format YYYY dan tidak boleh tahun lalu). Coba lagi atau Batal.", parse_mode='Markdown', reply_markup=batal_markup())
        bot.register_next_step_handler(message, set_year)
        return
    data = load_user_settings(message)
    data['year'] = value
    save_user_settings(message, data)
    bot.send_message(chat_id, "✅ *Tahun Kedaluwarsa disimpan*.", parse_mode='Markdown', reply_markup=settings_payment_markup())

def set_country(message):
    chat_id = message.chat.id
    if handle_batal_or_empty(message, set_country, "Nama negara tidak boleh kosong."): return
    
    value = message.text.strip()
    validation_result = validate_with_gemini(value, "full country name", chat_id)
    
    is_valid = validation_result.get('is_valid', False)
    suggestion = validation_result.get('suggestion')

    if is_valid and suggestion and value.lower() == suggestion.lower():
        final_value = suggestion.title()
        data = load_user_settings(message)
        data['country'] = final_value
        save_user_settings(message, data)
        bot.send_message(chat_id, f"✅ *Negara disimpan*: `{final_value}`.", parse_mode='Markdown', reply_markup=settings_account_markup(message))
    elif suggestion:
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        markup.add(types.KeyboardButton(f"Ya, gunakan '{suggestion}'"), types.KeyboardButton("Tidak, masukkan ulang"))
        markup.add(types.KeyboardButton("Batal"))
        msg = bot.send_message(chat_id, f"🤔 Maksud Anda *{suggestion}*? Mohon konfirmasi.", parse_mode='Markdown', reply_markup=markup)
        bot.register_next_step_handler(msg, lambda m: confirm_country_suggestion(m, message, suggestion))
    else:
        bot.send_message(chat_id, "⚠️ Nama negara tidak valid. Mohon periksa kembali ejaan Anda. Coba lagi atau Batal.", parse_mode='Markdown', reply_markup=batal_markup())
        bot.register_next_step_handler(message, set_country)

def confirm_country_suggestion(message, original_message, suggestion):
    chat_id = message.chat.id
    text = message.text.strip()

    if text.startswith("Ya, gunakan"):
        final_value = suggestion.title()
        data = load_user_settings(original_message)
        data['country'] = final_value
        save_user_settings(original_message, data)
        bot.send_message(chat_id, f"✅ *Negara disimpan*: `{final_value}`.", parse_mode='Markdown', reply_markup=settings_account_markup(message))
    elif text == "Tidak, masukkan ulang":
        msg = bot.send_message(chat_id, "Baik, silakan masukkan ulang nama negara:", reply_markup=batal_markup())
        bot.register_next_step_handler(msg, set_country)
    else:
        bot.send_message(chat_id, "✅ Pengaturan dibatalkan.", reply_markup=settings_account_markup(message))

def set_email_domain(message):
    chat_id = message.chat.id
    if handle_batal_or_empty(message, set_email_domain, "Domain email tidak boleh kosong."): return
    value = message.text.strip().lower()
    if '@' in value or ' ' in value or '.' not in value or len(value.split('.')[-1]) < 2:
        bot.send_message(chat_id, "⚠️ Format domain email tidak valid (contoh: `example.com`). Coba lagi atau Batal.", parse_mode='Markdown', reply_markup=batal_markup())
        bot.register_next_step_handler(message, set_email_domain)
        return
    data = load_user_settings(message)
    data['email_domain'] = value
    save_user_settings(message, data)
    bot.send_message(chat_id, "✅ *Domain email disimpan*.", parse_mode='Markdown', reply_markup=settings_account_markup(message))

def set_proxy_details(message):
    chat_id = message.chat.id
    if handle_batal_or_empty(message, set_proxy_details, "Input proxy tidak boleh kosong."): return
    
    value = message.text.strip()
    data = load_user_settings(message)

    if value.lower() == 'hapus':
        if 'proxy_string' in data:
            del data['proxy_string']
        data['use_proxy'] = False 
        save_user_settings(message, data)
        bot.send_message(chat_id, "✅ *Detail Proxy berhasil dihapus*. Proxy dinonaktifkan.", parse_mode='Markdown', reply_markup=settings_proxy_markup("Nonaktif"))
        return

    parts = value.split(':')
    if len(parts) not in [2, 4]:
        bot.send_message(chat_id, "⚠️ Format proxy tidak valid. Gunakan `IP:PORT` atau `IP:PORT:USER:PASS`. Coba lagi atau Batal.", parse_mode='Markdown', reply_markup=batal_markup())
        bot.register_next_step_handler(message, set_proxy_details)
        return
    
    if not webdriver_wire:
        bot.send_message(chat_id, "❌ *Modul `selenium-wire` tidak ditemukan*. Fitur proxy tidak akan berfungsi. Silakan instal dengan `pip install selenium-wire`.", parse_mode='Markdown', reply_markup=batal_markup())
        bot.register_next_step_handler(message, set_proxy_details)
        return

    bot.send_message(chat_id, "🔍 Memverifikasi proxy dan mendeteksi lokasi...", parse_mode='Markdown')
    proxy_info = get_proxy_info(value)

    if proxy_info:
        data['proxy_string'] = value
        data['use_proxy'] = True 
        save_user_settings(message, data)
        info_text = (
            f"✅ *Detail Proxy berhasil disimpan dan diverifikasi!*\n\n"
            f"📍 *Negara*: {proxy_info['country']} ({proxy_info['countryCode']})\n"
            f"🏙️ *Kota*: {proxy_info['city']}\n"
            f"🏢 *ISP*: {proxy_info['isp']}\n\n"
            f"Status Proxy: *Aktif*"
        )
        bot.send_message(chat_id, info_text, parse_mode='Markdown', reply_markup=settings_proxy_markup("Aktif"))
    else:
        bot.send_message(chat_id, "⚠️ *Proxy tidak dapat diverifikasi*. Pastikan proxy aktif dan dapat diakses. Pengaturan tidak disimpan. Coba lagi atau Batal.", parse_mode='Markdown', reply_markup=batal_markup())
        bot.register_next_step_handler(message, set_proxy_details)

def set_smshub_country_id_input(message):
    chat_id = message.chat.id
    if handle_batal_or_empty(message, set_smshub_country_id_input, "ID atau Nama Negara SMSHub tidak boleh kosong."): return
    
    user_input = message.text.strip()
    data = load_user_settings(message)

    country_id_found = None
    country_name_found = None

    # Try to match by ID first
    if user_input.isdigit() and user_input in SMSHUB_DATA:
        country_id_found = user_input
        country_name_found = SMSHUB_DATA[user_input]["name"]
    else: # Try to match by name (fuzzy or exact)
        input_lower = user_input.lower()
        for sms_id, sms_info in SMSHUB_DATA.items():
            # Exact match (case-insensitive)
            if sms_info["name"].lower() == input_lower or sms_info["original_country_name"] == input_lower:
                country_id_found = sms_id
                country_name_found = sms_info["name"]
                break
            # Fuzzy match (first word, contains)
            if input_lower in sms_info["name"].lower() or sms_info["name"].lower().startswith(input_lower.split()[0]):
                if not country_id_found: # Only set if no better match found yet
                    country_id_found = sms_id
                    country_name_found = sms_info["name"]
                elif len(sms_info["name"]) < len(country_name_found): # Prefer shorter, potentially more direct matches
                    country_id_found = sms_id
                    country_name_found = sms_info["name"]

    if country_id_found and country_name_found:
        data['smshub_country'] = country_id_found
        data['smshub_country_name'] = country_name_found
        save_user_settings(message, data)
        
        test_phone_code = get_country_phone_code(country_name_found) # Get phone code for the identified country
        
        # Now, proceed to ask for operator
        operators = SMSHUB_DATA[country_id_found].get("operators", [])
        
        if not operators:
            bot.send_message(chat_id, 
                             f"✅ *SMSHub Negara disimpan*: ID `{country_id_found}` (Nama: *{country_name_found}*).\n"
                             f"Kode Telepon yang terdeteksi untuk negara ini: `{test_phone_code}`.\n\n"
                             f"⚠️ *Tidak ada daftar operator yang tersedia* untuk negara ini dari data lokal. "
                             f"Silakan ketik `any` untuk memilih operator acak, atau `Batal`.", 
                             parse_mode='Markdown', 
                             reply_markup=batal_markup()) # Allow user to manually type 'any' or cancel
            bot.register_next_step_handler(message, set_smshub_operator_manual_fallback)
        else:
            markup_operators = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
            # Add 'any' option first, then sort other operators
            sorted_operators = sorted([op for op in operators if op != 'any'])
            markup_operators.add(types.KeyboardButton('Any')) # 'Any' button
            for op in sorted_operators:
                markup_operators.add(types.KeyboardButton(op.title())) # Capitalize for display
            markup_operators.add(types.KeyboardButton('Batal'))
            
            bot.send_message(chat_id, 
                             f"✅ *SMSHub Negara disimpan*: ID `{country_id_found}` (Nama: *{country_name_found}*).\n"
                             f"Kode Telepon yang terdeteksi untuk negara ini: `{test_phone_code}`.\n\n"
                             f"Sekarang, pilih *Operator SMSHub* yang tersedia untuk negara ini:", 
                             parse_mode='Markdown', 
                             reply_markup=markup_operators)
            bot.register_next_step_handler(message, select_smshub_operator)

    else:
        # If no direct or fuzzy match, prompt again
        bot.send_message(chat_id, 
                         "⚠️ ID atau Nama Negara tidak ditemukan dalam daftar SMSHub kami. "
                         "Mohon periksa kembali ID atau ejaan nama negara. "
                         "Daftar negara dan ID bisa dilihat di [sini](https://smshub.org/prices/get/en).\n\n"
                         "Coba lagi atau Batal.", 
                         parse_mode='Markdown', 
                         reply_markup=batal_markup(),
                         disable_web_page_preview=True)
        bot.register_next_step_handler(message, set_smshub_country_id_input)

# New function to handle operator selection from buttons
def select_smshub_operator(message):
    chat_id = message.chat.id
    if handle_batal_or_empty(message, select_smshub_operator, "Pilihan operator tidak boleh kosong."): return

    selected_operator = message.text.strip().lower()
    data = load_user_settings(message)
    smshub_country_id = data.get('smshub_country')

    if not smshub_country_id or str(smshub_country_id) not in SMSHUB_DATA:
        bot.send_message(chat_id, "⚠️ Terjadi kesalahan: Data negara SMSHub tidak ditemukan. Mohon ulangi pengaturan negara.", parse_mode='Markdown', reply_markup=settings_smshub_markup())
        return

    available_operators = SMSHUB_DATA[str(smshub_country_id)].get("operators", [])

    if selected_operator in available_operators or selected_operator == 'any': # 'any' is always a valid choice
        data['smshub_operator'] = selected_operator
        save_user_settings(message, data)
        bot.send_message(chat_id, f"✅ *SMSHub Operator disimpan*: `{selected_operator.title()}`.", parse_mode='Markdown', reply_markup=settings_smshub_markup())
    else:
        # This case should ideally not happen if buttons are used, but good for robustness
        bot.send_message(chat_id, 
                         f"⚠️ Operator *`{selected_operator.title()}`* tidak valid untuk negara yang dipilih. "
                         f"Silakan pilih dari tombol yang tersedia atau ketik 'any' jika tidak ada pilihan yang sesuai.", 
                         parse_mode='Markdown', 
                         reply_markup=batal_markup())
        bot.register_next_step_handler(message, select_smshub_operator)

# Fallback for when no operators are listed for a country, allowing manual 'any'
def set_smshub_operator_manual_fallback(message):
    chat_id = message.chat.id
    if handle_batal_or_empty(message, set_smshub_operator_manual_fallback, "Input operator tidak boleh kosong."): return
    
    user_input_operator = message.text.strip().lower()
    data = load_user_settings(message)

    if user_input_operator == "any":
        data['smshub_operator'] = user_input_operator
        save_user_settings(message, data)
        bot.send_message(chat_id, f"✅ *SMSHub Operator disimpan*: `{user_input_operator}` (operator apa saja).", parse_mode='Markdown', reply_markup=settings_smshub_markup())
    else:
        bot.send_message(chat_id, 
                         "⚠️ Operator tidak valid. Karena tidak ada daftar yang tersedia, Anda hanya dapat mengetik 'any' atau 'Batal'.", 
                         parse_mode='Markdown', 
                         reply_markup=batal_markup())
        bot.register_next_step_handler(message, set_smshub_operator_manual_fallback)


def set_smshub_max_price(message):
    chat_id = message.chat.id
    if handle_batal_or_empty(message, set_smshub_max_price, "Harga Maksimal SMSHub tidak boleh kosong."): return
    value = message.text.strip()
    try:
        price_val = float(value)
        if price_val < 0: raise ValueError
    except ValueError:
        bot.send_message(chat_id, "⚠️ Harga Maksimal SMSHub harus berupa angka positif. Coba lagi atau Batal.", parse_mode='Markdown', reply_markup=batal_markup())
        bot.register_next_step_handler(message, set_smshub_max_price)
        return
    data = load_user_settings(message)
    data['smshub_max_price'] = price_val
    save_user_settings(message, data)
    bot.send_message(chat_id, f"✅ *SMSHub Max Price disimpan*: `${value}`.", parse_mode='Markdown', reply_markup=settings_smshub_markup())

# =============== START BOT =================

if __name__ == '__main__':
    print("Bot AWS Signup siap dijalankan...")
    os.makedirs("user", exist_ok=True)
    
    # Load SMSHub data on startup
    SMSHUB_DATA = parse_smshub_data(COUNTRY_OPERATORS_FILE)
    if not SMSHUB_DATA:
        print(f"[WARNING] Tidak dapat memuat data SMSHub dari '{COUNTRY_OPERATORS_FILE}'. Fungsi terkait mungkin terbatas.")
    else:
        print(f"[INFO] Berhasil memuat {len(SMSHUB_DATA)} negara dari '{COUNTRY_OPERATORS_FILE}'.")


    if not webdriver_wire:
        print("\n[PERINGATAN] Modul 'selenium-wire' tidak ditemukan. Fitur proxy tidak akan berfungsi.\nJalankan 'pip install selenium-wire' untuk mengaktifkannya.\n")
    if Image is None:
        print("\n[PERINGATAN] Modul 'Pillow' tidak ditemukan. Fitur watermark tidak akan berfungsi.\nJalankan 'pip install Pillow' untuk mengaktifkannya.\n")
    
    # Ensure all handlers for manual_input_data are registered at the top level,
    # including the 3DS confirmation buttons.
    # We can use a regex handler for these specific button texts.
    @bot.message_handler(func=lambda message: message.text in ['✅ I have completed 3DS verification (redirected)', '❌ 3DS failed / Cancel'])
    def handle_3ds_button_response(message):
        chat_id = message.chat.id
        if chat_id in manual_input_data:
            manual_input_data[chat_id]['value'] = message.text
            manual_input_data[chat_id]['event'].set()
        else:
            bot.send_message(chat_id, "🤔 Respon tidak diharapkan saat ini. Kembali ke menu utama.", reply_markup=menu_utama_markup())


    bot.infinity_polling(timeout=60, long_polling_timeout = 30)