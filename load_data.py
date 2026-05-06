import json
from pathlib import Path
from database.db import init_db, insert_offers_bulk

def main():
    # 1. Initialiser la base de données (crée le fichier offers.db et la table)
    print("Initialisation de la base de données...")
    init_db()

    # 2. Charger le fichier JSON généré par ton scraper
    json_path = Path("data/indeed_offers.json")
    if not json_path.exists():
        print(f"Erreur : Le fichier {json_path} est introuvable.")
        return

    with open(json_path, "r", encoding="utf-8") as f:
        offers = json.load(f)

    # 3. Insérer les offres avec ta fonction bulk (qui gère les doublons)
    print(f"Tentative d'insertion de {len(offers)} offres...")
    inserted_count = insert_offers_bulk(offers)
    
    print(f"Succès ! {inserted_count} nouvelles offres ajoutées dans la base.")

if __name__ == "__main__":
    main()