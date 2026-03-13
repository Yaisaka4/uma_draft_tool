import requests
import json
import os
from bs4 import BeautifulSoup
from pathlib import Path

BASE_URL = "https://umamusume.jp"

CHAR_LIST = "https://umamusume.jp/character/"

ICON_DIR = "icons"
DB_DIR = "database"
WEB_DIR = "web"

headers = {
    "User-Agent": "Mozilla/5.0"
}


def get_character_pages():

    r = requests.get(CHAR_LIST, headers=headers)

    soup = BeautifulSoup(r.text, "html.parser")

    links = []

    for a in soup.select(".character__item a"):

        url = BASE_URL + a["href"]

        links.append(url)

    return links


def parse_character(url):

    r = requests.get(url, headers=headers)

    soup = BeautifulSoup(r.text, "html.parser")

    name = soup.select_one(".character__name")

    if name:
        name = name.text.strip()
    else:
        name = "Unknown"

    outfits = []

    for img in soup.select(".character__visual img"):

        icon = img["src"]

        outfits.append(icon)

    return name, outfits


def download_icon(url, filename):

    Path(ICON_DIR).mkdir(exist_ok=True)

    path = f"{ICON_DIR}/{filename}"

    if os.path.exists(path):
        return path

    r = requests.get(url)

    if r.status_code == 200:

        with open(path,"wb") as f:
            f.write(r.content)

    return path


def build_database():

    pages = get_character_pages()

    Path(DB_DIR).mkdir(exist_ok=True)

    database = []

    for url in pages:

        name, outfits = parse_character(url)

        for i, icon in enumerate(outfits):

            filename = f"{name}_{i}.png".replace(" ","_")

            icon_path = download_icon(icon, filename)

            entry = {
                "name": name,
                "outfit": i,
                "icon": icon_path
            }

            database.append(entry)

            print("Added:", name, "outfit", i)

    with open(f"{DB_DIR}/uma_database.json","w",encoding="utf8") as f:
        json.dump(database,f,indent=2,ensure_ascii=False)

    with open(f"{DB_DIR}/playable_uma.json","w",encoding="utf8") as f:
        json.dump(database,f,indent=2,ensure_ascii=False)

    return database


def generate_html(data):

    Path(WEB_DIR).mkdir(exist_ok=True)

    grid = ""

    for c in data:

        grid += f"""
        <div class="uma">
            <img src="../{c['icon']}">
            <p>{c['name']}</p>
        </div>
        """

    html = f"""
<html>
<head>
<style>

body {{
background:#111;
color:white;
font-family:sans-serif;
}}

.grid {{
display:grid;
grid-template-columns:repeat(auto-fill,120px);
gap:10px;
}}

.uma img {{
width:100px;
}}

</style>
</head>

<body>

<h1>UMA Draft</h1>

<div class="grid">
{grid}
</div>

</body>
</html>
"""

    with open(f"{WEB_DIR}/draft.html","w",encoding="utf8") as f:
        f.write(html)


def main():

    data = build_database()

    generate_html(data)

    print("\nDONE")
    print("Total outfits:", len(data))


if __name__ == "__main__":
    main()