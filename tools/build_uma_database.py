import requests
import sqlite3
import os
import json

BASE = "https://umapyoi.net/api/v1"

CHAR_LIST = BASE + "/character/list"
OUTFIT_API = BASE + "/outfit/character/"

ICON_DIR = "data/icons"
PORTRAIT_DIR = "data/portraits"
OUTFIT_DIR = "data/outfits"

DB_PATH = "data/uma.db"
JSON_PATH = "output/uma_characters.json"


def setup():

    os.makedirs(ICON_DIR, exist_ok=True)
    os.makedirs(PORTRAIT_DIR, exist_ok=True)
    os.makedirs(OUTFIT_DIR, exist_ok=True)
    os.makedirs("output", exist_ok=True)


def download(url, path):

    if not url:
        return None

    if os.path.exists(path):
        return path

    try:

        r = requests.get(url, timeout=30)

        if r.status_code == 200:

            with open(path, "wb") as f:
                f.write(r.content)

            return path

    except:
        pass

    return None


def get_characters():

    print("Fetching characters...")

    r = requests.get(CHAR_LIST)

    r.raise_for_status()

    chars = r.json()

    playable = []

    for c in chars:

        if not c.get("name_en"):
            continue

        playable.append(c)

    return playable


def get_outfits(cid):

    r = requests.get(OUTFIT_API + str(cid))

    if r.status_code != 200:
        return []

    return r.json()


def build_database(chars):

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS characters(
        id INTEGER PRIMARY KEY,
        name_en TEXT,
        name_jp TEXT,
        icon TEXT,
        portrait TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS outfits(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        character_id INTEGER,
        image TEXT
    )
    """)

    print("Downloading images and building database...")

    for c in chars:

        cid = c["id"]

        name_en = c.get("name_en")
        name_jp = c.get("name_jp")

        icon_url = c.get("thumb_img")
        portrait_url = c.get("image")

        icon_path = None
        portrait_path = None

        if icon_url:

            icon_path = download(
                icon_url,
                f"{ICON_DIR}/{cid}.png"
            )

        if portrait_url:

            portrait_path = download(
                portrait_url,
                f"{PORTRAIT_DIR}/{cid}.png"
            )

        cur.execute(
            "INSERT OR REPLACE INTO characters VALUES (?,?,?,?,?)",
            (cid, name_en, name_jp, icon_path, portrait_path)
        )

        outfits = get_outfits(cid)

        for o in outfits:

            img = o.get("image_url")

            if not img:
                continue

            outfit_file = f"{OUTFIT_DIR}/{cid}_{o['id']}.png"

            outfit_path = download(img, outfit_file)

            cur.execute(
                "INSERT INTO outfits(character_id,image) VALUES (?,?)",
                (cid, outfit_path)
            )

    conn.commit()
    conn.close()


def export_json():

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("""
    SELECT characters.id,name_en,name_jp,icon,portrait,image
    FROM characters
    LEFT JOIN outfits
    ON characters.id = outfits.character_id
    """)

    rows = cur.fetchall()

    data = []

    for r in rows:

        data.append({
            "id": r[0],
            "name_en": r[1],
            "name_jp": r[2],
            "icon": r[3],
            "portrait": r[4],
            "outfit": r[5]
        })

    with open(JSON_PATH, "w", encoding="utf8") as f:

        json.dump(data, f, ensure_ascii=False, indent=2)

    conn.close()


def main():

    setup()

    chars = get_characters()

    print("Playable characters:", len(chars))

    build_database(chars)

    export_json()

    print("Database build complete")


if __name__ == "__main__":
    main()