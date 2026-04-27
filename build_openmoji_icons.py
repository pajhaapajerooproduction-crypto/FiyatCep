import os
import re
import time
import urllib.request
import zipfile
from pathlib import Path

import pandas as pd

DATA_PACKAGE_ZIP = "FiyatCep_Data_Paketi_v9.zip"
ICON_MAP_FILE = "icon_map_openmoji.csv"
ICON_RULES_FILE = "icon_rules.csv"
ICON_DIR = Path("icons") / "openmoji"

TR_MAP = str.maketrans({
    "ı": "i", "İ": "i", "ş": "s", "ğ": "g", "ü": "u",
    "ö": "o", "ç": "c", "â": "a", "î": "i", "û": "u"
})

def clean(value):
    if pd.isna(value):
        return ""
    text = str(value).strip()
    return "" if text.lower() in ["nan", "none", "null", "<na>"] else text

def normalize(text):
    text = clean(text).lower().translate(TR_MAP)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()

def contains_keyword(normalized_text, normalized_keyword):
    if not normalized_text or not normalized_keyword:
        return False
    if " " in normalized_keyword:
        return f" {normalized_keyword} " in f" {normalized_text} "
    return normalized_keyword in normalized_text.split()

def read_products():
    if Path("products_master_clean.csv").exists():
        return pd.read_csv("products_master_clean.csv", dtype=str, encoding="utf-8-sig").fillna("")

    if Path(DATA_PACKAGE_ZIP).exists():
        with zipfile.ZipFile(DATA_PACKAGE_ZIP, "r") as z:
            with z.open("products_master_clean.csv") as f:
                return pd.read_csv(f, dtype=str, encoding="utf-8-sig").fillna("")

    raise FileNotFoundError("products_master_clean.csv veya FiyatCep_Data_Paketi_v9.zip bulunamadı.")

def read_rules():
    if not Path(ICON_RULES_FILE).exists():
        raise FileNotFoundError("icon_rules.csv bulunamadı.")

    df = pd.read_csv(ICON_RULES_FILE, dtype=str, encoding="utf-8-sig").fillna("")

    for col in ["keyword", "icon_group", "emoji", "openmoji_codepoint", "priority", "note"]:
        if col not in df.columns:
            df[col] = ""

    records = []
    for _, row in df.iterrows():
        keyword = clean(row.get("keyword", ""))
        if not keyword:
            continue
        try:
            priority = int(clean(row.get("priority", "")))
        except Exception:
            priority = 999

        records.append({
            "keyword": keyword,
            "keyword_norm": normalize(keyword),
            "icon_group": clean(row.get("icon_group", "")),
            "emoji": clean(row.get("emoji", "")),
            "openmoji_codepoint": clean(row.get("openmoji_codepoint", "")).upper(),
            "priority": priority,
            "note": clean(row.get("note", "")),
        })

    records.sort(key=lambda item: (item["priority"], -len(item["keyword_norm"])))
    return records

def match_rule(text, rules):
    n = normalize(text)

    for rule in rules:
        if contains_keyword(n, rule["keyword_norm"]):
            return rule

    return {}

def download_openmoji(codepoint):
    codepoint = clean(codepoint).upper()

    if not codepoint:
        return ""

    out_path = ICON_DIR / f"{codepoint}.svg"

    if out_path.exists() and out_path.stat().st_size > 0:
        return str(out_path).replace("\\", "/")

    url = f"https://raw.githubusercontent.com/hfg-gmuend/openmoji/master/color/svg/{codepoint}.svg"

    with urllib.request.urlopen(url, timeout=25) as resp:
        data = resp.read()

    if data.strip().startswith(b"<svg") or b"<svg" in data[:200]:
        ICON_DIR.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(data)
        return str(out_path).replace("\\", "/")

    return ""

def main():
    products = read_products()
    rules = read_rules()
    ICON_DIR.mkdir(parents=True, exist_ok=True)

    rows = []
    cache = {}

    for _, row in products.iterrows():
        product_id = clean(row.get("product_id", ""))

        if not product_id:
            continue

        text = " ".join(clean(row.get(c, "")) for c in [
            "urun_adi", "marka", "model", "ui_path",
            "ui_seviye_1", "ui_seviye_2", "ui_seviye_3", "ui_seviye_4",
            "sektor", "ana_kategori", "alt_kategori", "urun_turu"
        ])

        rule = match_rule(text, rules)

        icon_file = ""
        matched = "fallback"

        if rule:
            codepoint = rule.get("openmoji_codepoint", "")
            emoji = rule.get("emoji", "🛒")
            icon_group = rule.get("icon_group", "")
            query = rule.get("keyword", "")

            if codepoint:
                try:
                    if codepoint in cache:
                        icon_file = cache[codepoint]
                    else:
                        icon_file = download_openmoji(codepoint)
                        cache[codepoint] = icon_file
                    matched = "openmoji" if icon_file else "rule_emoji"
                except Exception as e:
                    print(f"Uyarı: {product_id} / {row.get('urun_adi','')} / {codepoint}: {e}")
                    matched = "rule_emoji"
                    time.sleep(0.05)
            else:
                matched = "rule_emoji"
        else:
            codepoint = ""
            emoji = "🛒"
            icon_group = "shopping"
            query = "fallback"

        rows.append({
            "product_id": product_id,
            "urun_adi": row.get("urun_adi", ""),
            "category": row.get("ui_path", ""),
            "icon_query": query,
            "icon_group": icon_group,
            "openmoji_codepoint": codepoint,
            "icon_id": f"openmoji:{codepoint.lower()}" if codepoint else "",
            "icon_file": icon_file,
            "emoji_fallback": emoji,
            "matched": matched,
        })

    pd.DataFrame(rows).to_csv(ICON_MAP_FILE, index=False, encoding="utf-8-sig")
    print(f"Tamamlandı: {ICON_MAP_FILE}")
    print(f"İkon klasörü: {ICON_DIR}")
    print("Şimdi uygulamayı yeniden çalıştır: streamlit run main.py")

if __name__ == "__main__":
    main()
