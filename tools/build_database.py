import requests
import os
import json
import time
from datetime import datetime
from urllib.parse import urlparse
from bs4 import BeautifulSoup

# --- Cấu hình ---
BASE_API = "https://umapyoi.net/api/v1"
CHAR_LIST = f"{BASE_API}/character/list"
CHAR_DETAIL = f"{BASE_API}/character"
OUTFIT_CHAR = f"{BASE_API}/outfit/character"
OUTFIT_GAMETORA = f"{BASE_API}/outfit"  # Sẽ thêm /{id}/gametora sau

RATE_LIMIT = 0.2

# Thư mục
DIRS = {
    "icons": "assets/icons",
    "portraits": "assets/portraits",
    "thumbs": "assets/thumbnails",
    "database": "database"
}

for d in DIRS.values():
    os.makedirs(d, exist_ok=True)

# --- Hàm tiện ích ---
def fetch_json(url):
    """Fetch JSON với xử lý lỗi"""
    try:
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            return r.json()
        else:
            print(f"  ⚠️ Lỗi {r.status_code}")
            return None
    except Exception as e:
        print(f"  ❌ Lỗi: {e}")
        return None

def follow_redirect(url):
    try:
        r = requests.get(url, allow_redirects=True, timeout=10)
        return r.url
    except Exception as e:
        print(f"    ❌ Lỗi redirect: {e}")
        return None

from bs4 import BeautifulSoup

def extract_largest_image(url):
    """
    Tìm ảnh lớn nhất trên trang GameTora
    """
    try:
        r = requests.get(url, timeout=10)
        if r.status_code != 200:
            return None

        soup = BeautifulSoup(r.text, "html.parser")

        images = []

        for img in soup.find_all("img"):
            src = img.get("src")
            if not src:
                continue

            # sửa URL tương đối
            if src.startswith("//"):
                src = "https:" + src
            elif src.startswith("/"):
                src = "https://gametora.com" + src

            images.append(src)

        largest = None
        largest_size = 0

        for img_url in images:
            try:
                head = requests.head(img_url, timeout=5)
                size = int(head.headers.get("content-length", 0))

                if size > largest_size:
                    largest_size = size
                    largest = img_url
            except:
                pass

        if largest:
            print(f"      🖼 Largest image: {largest}")

        return largest

    except Exception as e:
        print(f"      ❌ Parse lỗi: {e}")
        return None

def download_file(url, filepath):
    """Tải file với kiểm tra tồn tại"""
    if not url:
        return False
    if os.path.exists(filepath):
        return True
    try:
        r = requests.get(url, stream=True, timeout=15)
        if r.status_code != 200:
            return False
        with open(filepath, "wb") as f:
            for chunk in r.iter_content(1024):
                f.write(chunk)
        return True
    except Exception as e:
        print(f"    ❌ Lỗi tải: {e}")
        return False

def get_extension(url):
    """Lấy phần mở rộng file từ URL"""
    e = os.path.splitext(url.split("?")[0].split("/")[-1])[1]
    if e.lower() not in [".png", ".jpg", ".jpeg", ".webp"]:
        e = ".png"
    return e

# --- Bắt đầu xử lý ---
print("📋 Fetching character list...")
characters = fetch_json(CHAR_LIST)

if not characters:
    print("❌ Không thể lấy danh sách nhân vật")
    exit()

print(f"✅ Tìm thấy {len(characters)} nhân vật")

# Khởi tạo database
database = {
    "meta": {
        "generated": datetime.now().isoformat(),
        "source": "umapyoi+gametora",
        "version": "1.0"
    },
    "characters": []
}

stats = {
    "characters": 0,
    "outfits": 0,
    "icons": 0,
    "portraits": 0,
    "thumbnails": 0,
    "gametora_links": 0
}

# Xử lý từng nhân vật
for i, char in enumerate(characters):
    web_id = char.get("id")
    if not web_id:
        continue
    
    name = char.get("name_en") or char.get("name_jp") or f"Character_{web_id}"
    print(f"\n--- [{i+1}/{len(characters)}] {name} (ID: {web_id}) ---")
    
    # Lấy game_id
    print(f"  🔍 Lấy game_id...")
    detail = fetch_json(f"{CHAR_DETAIL}/{web_id}")
    
    if not detail:
        print(f"  ⚠️ Không lấy được chi tiết")
        continue
    
    game_id = detail.get("game_id")
    if not game_id:
        print(f"  ⚠️ Không có game_id")
        continue
    
    print(f"  ✅ game_id: {game_id}")
    
    # Tải thumbnail
    thumb_url = char.get("thumb_img")
    thumb_path = None
    if thumb_url:
        ext = get_extension(thumb_url)
        thumb_path = f"{DIRS['thumbs']}/{web_id}{ext}"
        if download_file(thumb_url, thumb_path):
            stats["thumbnails"] += 1
            print(f"  ✅ Đã tải thumbnail")
    
    # Lấy outfits bằng game_id
    print(f"  👕 Đang lấy outfits...")
    outfits = fetch_json(f"{OUTFIT_CHAR}/{game_id}")
    
    char_data = {
        "id": web_id,
        "game_id": game_id,
        "name": name,
        "name_en": char.get("name_en"),
        "name_jp": char.get("name_jp"),
        "thumbnail": thumb_path,
        "outfits": []
    }
    
    if outfits and isinstance(outfits, list):
        print(f"  📦 Tìm thấy {len(outfits)} outfits")
        
        for outfit in outfits:
            outfit_id = outfit.get("id")
            if not outfit_id:
                continue
            
            title = (outfit.get("title_en") or 
                    outfit.get("title") or 
                    f"Outfit_{outfit_id}")
            
            print(f"    Outfit {outfit_id}: {title[:30]}...")
            
            # Gọi endpoint /gametora để lấy redirect URL
            gametora_url = follow_redirect(f"{OUTFIT_GAMETORA}/{outfit_id}/gametora")
            
            icon_path = None
            portrait_path = None
            
            if gametora_url:
                stats["gametora_links"] += 1
                print(f"      ✅ Got GameTora link")
                
                # Thử lấy ảnh từ GameTora
                largest_img = extract_largest_image(gametora_url)

                icon_url = largest_img
                portrait_url = largest_img
                
                # Tải icon
                if icon_url:
                    ext = get_extension(icon_url)
                    icon_path = f"{DIRS['icons']}/{outfit_id}{ext}"
                    if download_file(icon_url, icon_path):
                        stats["icons"] += 1
                        print(f"      ✅ Đã tải icon")
                
                # Tải portrait
                if portrait_url and portrait_url != icon_url:
                    ext = get_extension(portrait_url)
                    portrait_path = f"{DIRS['portraits']}/{outfit_id}{ext}"
                    if download_file(portrait_url, portrait_path):
                        stats["portraits"] += 1
                        print(f"      ✅ Đã tải portrait")
            
            # Thêm vào database
            char_data["outfits"].append({
                "id": outfit_id,
                "name": title,
                "gametora_url": gametora_url,
                "icon": icon_path,
                "portrait": portrait_path,
                "rarity": outfit.get("default_rarity"),
                "running_style": outfit.get("running_style")
            })
            
            stats["outfits"] += 1
            time.sleep(RATE_LIMIT)
    
    database["characters"].append(char_data)
    stats["characters"] += 1
    time.sleep(RATE_LIMIT)

# Lưu database
output_path = f"{DIRS['database']}/uma_database.json"
with open(output_path, "w", encoding="utf8") as f:
    json.dump(database, f, ensure_ascii=False, indent=2)

# In kết quả
print(f"\n{'='*60}")
print("✅ BUILD COMPLETE")
print(f"{'='*60}")
print(f"📊 THỐNG KÊ:")
print(f"   - Characters: {stats['characters']}")
print(f"   - Outfits: {stats['outfits']}")
print(f"   - GameTora links: {stats['gametora_links']}")
print(f"   - Thumbnails: {stats['thumbnails']}")
print(f"   - Icons: {stats['icons']}")
print(f"   - Portraits: {stats['portraits']}")
print(f"\n📁 Database: {output_path}")
print(f"{'='*60}")