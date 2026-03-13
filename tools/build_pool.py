import json

with open("../database/characters.json","r") as f:

    db=json.load(f)

units=[]

for c in db["characters"]:

    for o in c["outfits"]:

        units.append({
            "id":o["id"],
            "name":c["name"]+" "+o["name"]
        })

print(len(units),"units")