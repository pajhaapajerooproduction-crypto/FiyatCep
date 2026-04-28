import os
import re
import base64
import uuid
import zipfile
import urllib.parse
from datetime import datetime

import pandas as pd
import streamlit as st

try:
    import folium
    from streamlit_folium import st_folium
    HAS_MAP = True
except Exception:
    HAS_MAP = False

try:
    from streamlit_geolocation import streamlit_geolocation
    HAS_GEOLOCATION = True
except Exception:
    HAS_GEOLOCATION = False


# =========================================================
# FİYATCEP - ADİSYON/FİŞ MANTIĞI V1
# =========================================================
# Gerekli dosyalar:
# - products_master_clean.csv
# - source_master.csv
# Opsiyonel:
# - product_specs.csv veya product_specs_template.csv
# - data_reference.csv veya data_reference_template.csv
#
# Not:
# Bu kod kategori/mağaza/marka UYDURMAZ.
# Ekranda görünen ürün ağacı products_master_clean.csv içinden gelir.
# Kaynak listesi source_master.csv içinden gelir.
# Kullanıcı isterse elle kaynak yazabilir; bu kullanıcı girdisidir, otomatik uydurma değildir.
# =========================================================


# =========================================================
# 1. AYARLAR
# =========================================================

PRODUCTS_FILE = "products_master_clean.csv"
SOURCE_FILE = "source_master.csv"

SPECS_FILE = "product_specs.csv"
SPECS_TEMPLATE_FILE = "product_specs_template.csv"

DATA_REFERENCE_FILE = "data_reference.csv"
DATA_REFERENCE_TEMPLATE_FILE = "data_reference_template.csv"

RECEIPT_HEADER_FILE = "receipt_header.csv"
PRICE_RECORDS_FILE = "price_records.csv"
RESEARCH_SESSIONS_FILE = "research_sessions.csv"
SHOPPING_SESSIONS_FILE = "shopping_sessions.csv"
SHOPPING_ITEMS_FILE = "shopping_items.csv"
USER_LISTS_FILE = "user_shopping_lists.csv"
USER_LIST_ITEMS_FILE = "user_shopping_list_items.csv"

DATA_PACKAGE_ZIP = "FiyatCep_Data_Paketi_v9.zip"
ICON_MAP_FILE = "icon_map_openmoji.csv"
ICON_RULES_FILE = "icon_rules.csv"
ICON_DIR = os.path.join("icons", "openmoji")

RECEIPT_HEADER_COLUMNS = [
    "receipt_id",
    "research_id",
    "tarih",
    "saat",
    "source_id",
    "source_type",
    "source_name",
    "konum_lat",
    "konum_lon",
    "konum_dogrulandi",
    "toplam_kalem",
    "not",
]

PRICE_RECORD_COLUMNS = [
    "receipt_id",
    "research_id",
    "line_id",
    "tarih",
    "saat",
    "source_id",
    "source_type",
    "source_name",
    "product_id",
    "urun_adi",
    "marka",
    "model",
    "varyant",
    "birim",
    "fiyat",
    "konum_lat",
    "konum_lon",
    "not",
]

RESEARCH_SESSION_COLUMNS = [
    "research_id",
    "status",
    "mode",
    "baslangic_tarih",
    "baslangic_saat",
    "bitis_tarih",
    "bitis_saat",
    "not",
]

SHOPPING_SESSION_COLUMNS = [
    "shopping_id",
    "research_id",
    "status",
    "tarih",
    "saat",
    "toplam",
    "tasarruf",
    "tamamlanan_urun",
    "toplam_urun",
    "not",
]

SHOPPING_ITEM_COLUMNS = [
    "shopping_id",
    "research_id",
    "product_id",
    "urun",
    "source_name",
    "source_type",
    "birim",
    "fiyat",
    "tasarruf",
    "durum",
    "tarih",
    "saat",
]


USER_LIST_COLUMNS = [
    "list_id",
    "status",
    "tarih",
    "saat",
    "ad",
    "not",
]

USER_LIST_ITEM_COLUMNS = [
    "list_id",
    "product_id",
    "urun",
    "birim",
    "tarih",
    "saat",
]


st.set_page_config(
    page_title="FiyatCep",
    page_icon="🧾",
    layout="centered",
    initial_sidebar_state="collapsed",
)


# =========================================================
# 2. GENEL YARDIMCI FONKSİYONLAR
# =========================================================

def clean_cell(value):
    if pd.isna(value):
        return ""
    text = str(value).strip()
    if text.lower() in ["nan", "none", "null", "<na>"]:
        return ""
    return text


def normalize_for_search(text):
    text = clean_cell(text).lower()

    tr_map = str.maketrans({
        "ı": "i",
        "İ": "i",
        "ş": "s",
        "ğ": "g",
        "ü": "u",
        "ö": "o",
        "ç": "c",
        "â": "a",
        "î": "i",
        "û": "u",
    })

    text = text.translate(tr_map)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def compact_join(values, sep=" "):
    output = []
    seen = set()

    for value in values:
        value = clean_cell(value)
        key = normalize_for_search(value)

        if value and key and key not in seen:
            output.append(value)
            seen.add(key)

    return sep.join(output)


def ensure_columns(df, columns):
    for col in columns:
        if col not in df.columns:
            df[col] = ""
    return df


def safe_key(prefix, *values):
    """
    Streamlit widget key üretir.
    Eski kullanım: safe_key(prefix, value, idx)
    Yeni kullanım: safe_key(prefix, value1, value2, value3...)
    """
    raw = "_".join([clean_cell(prefix)] + [clean_cell(v) for v in values])
    return normalize_for_search(raw).replace(" ", "_")[:180]


def parse_price(value):
    value = clean_cell(value)

    if not value:
        return None

    value = value.replace("₺", "").replace("TL", "").replace("tl", "")
    value = value.replace(".", "").replace(",", ".") if "," in value else value

    try:
        price = float(value)
        if price <= 0:
            return None
        return round(price, 2)
    except Exception:
        return None


def format_price(value):
    price = parse_price(value)

    if price is None:
        return ""

    return f"{price:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")



def read_saved_price_records():
    if not os.path.exists(PRICE_RECORDS_FILE):
        return pd.DataFrame(columns=PRICE_RECORD_COLUMNS)

    try:
        df = pd.read_csv(PRICE_RECORDS_FILE, dtype=str, encoding="utf-8-sig")
    except UnicodeDecodeError:
        df = pd.read_csv(PRICE_RECORDS_FILE, dtype=str, encoding="cp1254")
    except Exception:
        return pd.DataFrame(columns=PRICE_RECORD_COLUMNS)

    df = ensure_columns(df, PRICE_RECORD_COLUMNS)

    for col in PRICE_RECORD_COLUMNS:
        df[col] = df[col].apply(clean_cell)

    df["price_float"] = df["fiyat"].apply(parse_price)
    df = df[df["price_float"].notna()].copy()

    return df


def make_current_receipt_df():
    rows = []

    for item in st.session_state.receipt_items:
        rows.append({
            "product_id": clean_cell(item.get("product_id", "")),
            "urun_adi": clean_cell(item.get("urun_adi", "")),
            "title": clean_cell(item.get("title", "")),
            "marka": clean_cell(item.get("marka", "")),
            "model": clean_cell(item.get("model", "")),
            "birim": clean_cell(item.get("birim", "")),
            "path": clean_cell(item.get("path", "")),
        })

    return pd.DataFrame(rows)



def make_saved_receipt_df(saved_df, receipt_id=""):
    if saved_df.empty:
        return pd.DataFrame()

    work = saved_df.copy()

    if receipt_id:
        work = work[work["receipt_id"] == receipt_id].copy()

    if work.empty:
        return pd.DataFrame()

    # Eğer receipt_id verilmediyse en son kaydedilen fişi bul.
    if not receipt_id:
        latest = (
            work.sort_values(["tarih", "saat"], ascending=[False, False])
            .iloc[0]["receipt_id"]
        )
        work = work[work["receipt_id"] == latest].copy()
        st.session_state.compare_receipt_id = latest

    rows = []

    for product_id, group in work.groupby("product_id"):
        first = group.iloc[0]
        rows.append({
            "product_id": clean_cell(first.get("product_id", "")),
            "urun_adi": clean_cell(first.get("urun_adi", "")),
            "title": compact_join([
                first.get("marka", ""),
                first.get("model", ""),
                first.get("urun_adi", ""),
            ]),
            "marka": clean_cell(first.get("marka", "")),
            "model": clean_cell(first.get("model", "")),
            "birim": clean_cell(first.get("birim", "")),
            "path": "",
        })

    return pd.DataFrame(rows)



def get_compare_research_id(saved_df=None):
    research_id = clean_cell(st.session_state.get("active_research_id", ""))

    if research_id:
        return research_id

    research_id = clean_cell(st.session_state.get("compare_research_id", ""))

    if research_id:
        return research_id

    if saved_df is not None and not saved_df.empty and "research_id" in saved_df.columns:
        non_empty = saved_df[saved_df["research_id"] != ""].copy()
        if not non_empty.empty:
            latest = non_empty.sort_values(["tarih", "saat"], ascending=[False, False]).iloc[0]
            return latest["research_id"]

    return ""


def make_research_products_df(saved_df):
    if saved_df.empty:
        return pd.DataFrame()

    rows = []

    for product_id, group in saved_df.groupby("product_id"):
        first = group.sort_values(["tarih", "saat"], ascending=[False, False]).iloc[0]
        rows.append({
            "product_id": clean_cell(first.get("product_id", "")),
            "urun_adi": clean_cell(first.get("urun_adi", "")),
            "title": compact_join([
                first.get("marka", ""),
                first.get("model", ""),
                first.get("urun_adi", ""),
            ]),
            "marka": clean_cell(first.get("marka", "")),
            "model": clean_cell(first.get("model", "")),
            "birim": clean_cell(first.get("birim", "")),
            "path": "",
        })

    return pd.DataFrame(rows)


def compute_cheapest_plan(current_df, saved_df):
    """
    Aktif fiyat araştırmasındaki kayıtlar üzerinden:
    - ürün bazında en ucuz kaynak
    - ürün bazında en yüksek kaynak
    - tahmini tasarruf
    - kaynak/durak bazında rota bölümleri
    üretir.
    """
    if current_df.empty or saved_df.empty:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    current_ids = current_df["product_id"].dropna().astype(str).tolist()
    relevant = saved_df[saved_df["product_id"].isin(current_ids)].copy()

    if relevant.empty:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    relevant = relevant.sort_values(["product_id", "price_float", "tarih", "saat"], ascending=[True, True, False, False])

    cheapest_rows = []

    for product_id, group in relevant.groupby("product_id"):
        product_info = current_df[current_df["product_id"] == product_id].iloc[0].to_dict()

        best = group.sort_values(["price_float", "tarih", "saat"], ascending=[True, False, False]).iloc[0].to_dict()
        worst = group.sort_values(["price_float", "tarih", "saat"], ascending=[False, False, False]).iloc[0].to_dict()

        best_price = float(best.get("price_float", 0))
        worst_price = float(worst.get("price_float", best_price))
        saving = max(0.0, worst_price - best_price)

        cheapest_rows.append({
            "product_id": product_id,
            "urun": product_info.get("title") or product_info.get("urun_adi"),
            "birim": product_info.get("birim", ""),
            "path": product_info.get("path", ""),
            "en_ucuz_fiyat": round(best_price, 2),
            "en_yuksek_fiyat": round(worst_price, 2),
            "tasarruf": round(saving, 2),
            "source_name": best.get("source_name", ""),
            "source_type": best.get("source_type", ""),
            "tarih": best.get("tarih", ""),
            "saat": best.get("saat", ""),
            "worst_source_name": worst.get("source_name", ""),
            "worst_source_type": worst.get("source_type", ""),
        })

    cheapest_df = pd.DataFrame(cheapest_rows)

    # Aynı ürün master datada birden fazla product_id ile geçiyorsa
    # rotada iki ayrı kutu olarak görünmesin.
    # Örn: Biber Çarliston farklı product_id'lerle kayıtlıysa,
    # rota için tek ürün kabul edilir ve en ucuz fiyat seçilir.
    if not cheapest_df.empty:
        cheapest_df["_route_key"] = cheapest_df.apply(
            lambda row: normalize_for_search(
                compact_join([
                    row.get("urun", ""),
                    row.get("birim", ""),
                ])
            ),
            axis=1
        )

        collapsed_rows = []

        for _, dup_group in cheapest_df.groupby("_route_key"):
            dup_group = dup_group.copy()

            best = dup_group.sort_values(
                ["en_ucuz_fiyat", "tarih", "saat"],
                ascending=[True, False, False]
            ).iloc[0].to_dict()

            max_price = float(dup_group["en_yuksek_fiyat"].max())
            min_price = float(dup_group["en_ucuz_fiyat"].min())

            best["en_yuksek_fiyat"] = round(max_price, 2)
            best["tasarruf"] = round(max(0.0, max_price - min_price), 2)

            collapsed_rows.append(best)

        cheapest_df = pd.DataFrame(collapsed_rows).drop(columns=["_route_key"], errors="ignore")

    stop_rows = []
    if not cheapest_df.empty:
        for source_name, group in cheapest_df.groupby("source_name"):
            stop_rows.append({
                "source_name": source_name,
                "source_type": compact_join(group["source_type"].dropna().unique(), sep=", "),
                "urun_sayisi": len(group),
                "toplam": round(float(group["en_ucuz_fiyat"].sum()), 2),
                "tasarruf": round(float(group["tasarruf"].sum()), 2),
                "urunler": " | ".join(group["urun"].astype(str).tolist()),
            })

    stop_df = pd.DataFrame(stop_rows)
    if not stop_df.empty:
        stop_df = stop_df.sort_values(["toplam", "urun_sayisi"], ascending=[True, False])

    single_stop_rows = []
    for source_name, group in relevant.groupby("source_name"):
        best_per_product = group.sort_values("price_float").groupby("product_id").head(1)
        single_stop_rows.append({
            "source_name": source_name,
            "source_type": compact_join(best_per_product["source_type"].dropna().unique(), sep=", "),
            "bulunan_urun": best_per_product["product_id"].nunique(),
            "toplam_urun": len(current_df),
            "eksik_urun": len(current_df) - best_per_product["product_id"].nunique(),
            "toplam": round(float(best_per_product["price_float"].sum()), 2),
        })

    single_stop_df = pd.DataFrame(single_stop_rows)

    if not single_stop_df.empty:
        single_stop_df = single_stop_df.sort_values(
            ["eksik_urun", "toplam", "bulunan_urun"],
            ascending=[True, True, False]
        )

    return cheapest_df, stop_df, single_stop_df

def is_electronics_row(row):
    text = compact_join([
        row.get("sektor", ""),
        row.get("ana_kategori", ""),
        row.get("alt_kategori", ""),
        row.get("urun_turu", ""),
        row.get("ui_seviye_1", ""),
        row.get("ui_seviye_2", ""),
        row.get("ui_seviye_3", ""),
        row.get("ui_seviye_4", ""),
        row.get("ui_path", ""),
    ])
    n = normalize_for_search(text)
    return any(key in n for key in ["elektronik", "telefon", "bilgisayar", "tablet", "beyaz esya", "ev aletleri"])


def compact_electronic_title(base, marka=""):
    """
    Elektronik ürün kartlarında yazı kalabalığını azaltır.
    Örn:
    Samsung Galaxy A07 4 GB RAM 128 GB Hafıza -> Samsung Galaxy A07 4/128
    Apple iPhone 17 512 GB MG6P4TU/A -> Apple iPhone 17 512 GB
    """
    text = clean_cell(base)

    if not text:
        return ""

    # Tekrar eden ürün adı varsa yarıya düşür.
    words = text.split()

    if len(words) % 2 == 0:
        half = len(words) // 2
        if [w.lower() for w in words[:half]] == [w.lower() for w in words[half:]]:
            text = " ".join(words[:half])

    # Apple ürün kodları / stok kodları temizliği.
    text = re.sub(r"\b[A-Z0-9]{4,}TU/A\b", "", text)
    text = re.sub(r"\bM[A-Z0-9]{3,}/A\b", "", text)
    text = re.sub(r"\b[A-Z0-9]{6,}/A\b", "", text)

    # Telefonlarda RAM/Hafıza uzun yazımını 4/128 gibi kısalt.
    ram = ""
    storage = ""

    ram_match = re.search(r"\b(\d{1,2})\s*GB\s*(?:RAM|Ram|ram)\b", text)
    storage_match = re.search(
        r"\b(\d{2,4})\s*GB\s*(?:Hafıza|Hafiza|Depolama|Dahili Hafıza|Dahili Hafiza|ROM|Rom|rom)?\b",
        text
    )

    if ram_match:
        ram = ram_match.group(1)

    # storage_match RAM ile aynı yeri göstermesin diye tüm GB'leri kontrol et.
    gb_values = re.findall(r"\b(\d{1,4})\s*GB\b", text)

    if gb_values:
        values = [int(v) for v in gb_values if v.isdigit()]
        storage_candidates = [v for v in values if v >= 16]

        if storage_candidates:
            storage = str(max(storage_candidates))

    if ram and storage:
        text = re.sub(r"\b\d{1,2}\s*GB\s*(?:RAM|Ram|ram)\b", "", text)
        text = re.sub(
            r"\b\d{2,4}\s*GB\s*(?:Hafıza|Hafiza|Depolama|Dahili Hafıza|Dahili Hafiza|ROM|Rom|rom)?\b",
            "",
            text
        )

        # Fazla açıklama kelimeleri.
        text = re.sub(r"\b(?:Akıllı Telefon|Akilli Telefon|Cep Telefonu|Telefon)\b", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\b(?:Çift Hat|Cift Hat|Dual Sim|SIM)\b", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s+", " ", text).strip(" -_/|")

        text = f"{text} {ram}/{storage}"

    else:
        # Elektronikte ürün türünü tekrar eden uzun kalıpları temizle.
        text = re.sub(r"\b(?:Akıllı Telefon|Akilli Telefon|Cep Telefonu)\b", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\b(?:Şarjlı Dikey Süpürge|Sarjli Dikey Supurge|Dikey Süpürge|Dikey Supurge)\b", "Dikey Süpürge", text, flags=re.IGNORECASE)
        text = re.sub(r"\b(?:Buzdolabı|Buzdolabi)\s+(?:Buzdolabı|Buzdolabi)\b", "Buzdolabı", text, flags=re.IGNORECASE)

    text = re.sub(r"\s+", " ", text).strip(" -_/|")

    # Marka base içinde yoksa ekle; ama tekrar etmiyorsa.
    if marka and normalize_for_search(marka) not in normalize_for_search(text):
        text = compact_join([marka, text])

    # Uzun teknik açıklamaları kırp.
    if len(text) > 52:
        text = text[:49].rstrip() + "..."

    return text


def format_product_title(row):
    marka = clean_cell(row.get("marka", ""))
    model = clean_cell(row.get("model", ""))
    urun_adi = clean_cell(row.get("urun_adi", ""))

    base = model or urun_adi or marka

    if not base:
        base = urun_adi

    if is_electronics_row(row):
        compact = compact_electronic_title(base, marka=marka)
        return compact or "İsimsiz Ürün"

    if marka and normalize_for_search(marka) not in normalize_for_search(base):
        base = compact_join([marka, base])

    words = base.split()

    if len(words) % 2 == 0:
        half = len(words) // 2
        if [w.lower() for w in words[:half]] == [w.lower() for w in words[half:]]:
            base = " ".join(words[:half])

    if marka.lower() == "apple":
        base = re.sub(r"\b[A-Z0-9]{4,}TU/A\b", "", base)
        base = re.sub(r"\bM[A-Z0-9]{3,}/A\b", "", base)
        base = re.sub(r"\b[A-Z0-9]{6,}/A\b", "", base)

    base = re.sub(r"\s+", " ", base).strip()

    if len(base) > 70:
        base = base[:67] + "..."

    return base or "İsimsiz Ürün"


def format_product_subtitle(row):
    return compact_join([
        row.get("sektor", ""),
        row.get("ana_kategori", ""),
        row.get("alt_kategori", ""),
        row.get("urun_turu", ""),
    ], sep=" > ")


def get_today_strings():
    now = datetime.now()
    return now.strftime("%Y-%m-%d"), now.strftime("%H:%M:%S")


def append_csv(file_path, rows, columns):
    if not rows:
        return

    df_new = pd.DataFrame(rows)
    df_new = ensure_columns(df_new, columns)[columns]

    if os.path.exists(file_path):
        try:
            df_old = pd.read_csv(file_path, dtype=str, encoding="utf-8-sig")
            all_cols = list(dict.fromkeys(list(df_old.columns) + columns))

            df_old = ensure_columns(df_old, all_cols)
            df_new = ensure_columns(df_new, all_cols)

            df_out = pd.concat([df_old[all_cols], df_new[all_cols]], ignore_index=True)

        except Exception:
            df_out = df_new
    else:
        df_out = df_new

    df_out.to_csv(file_path, index=False, encoding="utf-8-sig")


# =========================================================
# 3. DOSYA OKUMA
# =========================================================


def read_research_sessions():
    if not os.path.exists(RESEARCH_SESSIONS_FILE):
        return pd.DataFrame(columns=RESEARCH_SESSION_COLUMNS)

    try:
        df = pd.read_csv(RESEARCH_SESSIONS_FILE, dtype=str, encoding="utf-8-sig")
    except UnicodeDecodeError:
        df = pd.read_csv(RESEARCH_SESSIONS_FILE, dtype=str, encoding="cp1254")
    except Exception:
        return pd.DataFrame(columns=RESEARCH_SESSION_COLUMNS)

    df = ensure_columns(df, RESEARCH_SESSION_COLUMNS)

    for col in RESEARCH_SESSION_COLUMNS:
        df[col] = df[col].apply(clean_cell)

    return df[RESEARCH_SESSION_COLUMNS]


def write_research_sessions(df):
    df = ensure_columns(df, RESEARCH_SESSION_COLUMNS)[RESEARCH_SESSION_COLUMNS]
    df.to_csv(RESEARCH_SESSIONS_FILE, index=False, encoding="utf-8-sig")


def upsert_research_session(row):
    df = read_research_sessions()

    if df.empty or row["research_id"] not in df["research_id"].tolist():
        df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    else:
        idx = df.index[df["research_id"] == row["research_id"]][0]
        for key, value in row.items():
            if key in df.columns:
                df.at[idx, key] = value

    write_research_sessions(df)


def start_research_session(mode="Bugün alacağım"):
    tarih, saat = get_today_strings()
    research_id = "AR_" + datetime.now().strftime("%Y%m%d%H%M%S") + "_" + uuid.uuid4().hex[:5]

    row = {
        "research_id": research_id,
        "status": "açık",
        "mode": mode,
        "baslangic_tarih": tarih,
        "baslangic_saat": saat,
        "bitis_tarih": "",
        "bitis_saat": "",
        "not": "",
    }

    upsert_research_session(row)

    st.session_state.active_research_id = research_id
    st.session_state.active_research_mode = mode
    st.session_state.research_active = True
    st.session_state.compare_research_id = research_id
    st.session_state.current_shopping_id = ""
    st.session_state.shopping_checked = {}
    st.session_state.route_excluded_products = []
    st.session_state.route_excluded_sources = []
    st.session_state.step = "product_tree"


def finish_research_session():
    research_id = clean_cell(st.session_state.get("active_research_id", ""))

    if not research_id:
        st.warning("Açık fiyat araştırması yok.")
        return

    sessions = read_research_sessions()
    current = sessions[sessions["research_id"] == research_id]

    tarih, saat = get_today_strings()

    if current.empty:
        row = {
            "research_id": research_id,
            "status": "kapalı",
            "mode": st.session_state.get("active_research_mode", ""),
            "baslangic_tarih": "",
            "baslangic_saat": "",
            "bitis_tarih": tarih,
            "bitis_saat": saat,
            "not": "",
        }
    else:
        row = current.iloc[0].to_dict()
        row["status"] = "kapalı"
        row["bitis_tarih"] = tarih
        row["bitis_saat"] = saat

    upsert_research_session(row)

    st.session_state.research_active = False
    st.session_state.compare_research_id = research_id
    st.session_state.active_research_id = ""
    st.session_state.active_research_mode = ""
    st.session_state.step = "compare_prices"



def continue_research_session(research_id):
    """
    Eski bir fiyat araştırmasını yeniden aktif eder.
    Sonradan farklı mağaza/konum fiyatı girilecekse aynı research_id altında devam eder.
    Böylece En Ucuz/Rota eski + yeni fişleri birlikte kıyaslar.
    """
    research_id = clean_cell(research_id)

    if not research_id:
        st.warning("Devam edilecek fiyat araştırması bulunamadı.")
        return

    sessions = read_research_sessions()
    current = sessions[sessions["research_id"] == research_id].copy()

    tarih, saat = get_today_strings()

    if current.empty:
        row = {
            "research_id": research_id,
            "status": "açık",
            "mode": "Geniş fiyat araştırması",
            "baslangic_tarih": tarih,
            "baslangic_saat": saat,
            "bitis_tarih": "",
            "bitis_saat": "",
            "not": "",
        }
    else:
        row = current.iloc[0].to_dict()
        row["status"] = "açık"
        row["bitis_tarih"] = ""
        row["bitis_saat"] = ""

    upsert_research_session(row)

    st.session_state.active_research_id = research_id
    st.session_state.active_research_mode = clean_cell(row.get("mode", "")) or "Geniş fiyat araştırması"
    st.session_state.research_active = True
    st.session_state.compare_research_id = research_id
    st.session_state.research_history_index = 0

    # Yeni fiyat girişi yeni fiş demek; kaynak/konum yeniden doğrulansın.
    st.session_state.receipt_items = []
    st.session_state.source_id = ""
    st.session_state.source_type = ""
    st.session_state.source_name = ""
    st.session_state.source_auto_selected = False
    st.session_state.location_confirmed = False
    st.session_state.needs_location_update = True

    st.session_state.current_shopping_id = ""
    st.session_state.shopping_checked = {}
    st.session_state.route_excluded_products = []
    st.session_state.route_excluded_sources = []

    st.session_state.step = "location"


def delete_research_session(research_id):
    """
    Fiyat araştırmasını ve ona bağlı kayıtlı fiş/fiyat kayıtlarını siler.
    Bağlı alışveriş planlarını da temizler.
    """
    research_id = clean_cell(research_id)

    if not research_id:
        return

    sessions = read_research_sessions()

    if not sessions.empty:
        sessions = sessions[sessions["research_id"] != research_id].copy()
        write_research_sessions(sessions)

    # Receipt header temizliği
    if os.path.exists(RECEIPT_HEADER_FILE):
        try:
            headers = pd.read_csv(RECEIPT_HEADER_FILE, dtype=str, encoding="utf-8-sig").fillna("")
        except UnicodeDecodeError:
            headers = pd.read_csv(RECEIPT_HEADER_FILE, dtype=str, encoding="cp1254").fillna("")
        except Exception:
            headers = pd.DataFrame(columns=RECEIPT_HEADER_COLUMNS)

        if "research_id" in headers.columns:
            headers = headers[headers["research_id"] != research_id].copy()
            headers = ensure_columns(headers, RECEIPT_HEADER_COLUMNS)[RECEIPT_HEADER_COLUMNS]
            headers.to_csv(RECEIPT_HEADER_FILE, index=False, encoding="utf-8-sig")

    # Price records temizliği
    if os.path.exists(PRICE_RECORDS_FILE):
        try:
            records = pd.read_csv(PRICE_RECORDS_FILE, dtype=str, encoding="utf-8-sig").fillna("")
        except UnicodeDecodeError:
            records = pd.read_csv(PRICE_RECORDS_FILE, dtype=str, encoding="cp1254").fillna("")
        except Exception:
            records = pd.DataFrame(columns=PRICE_RECORD_COLUMNS)

        if "research_id" in records.columns:
            records = records[records["research_id"] != research_id].copy()
            records = ensure_columns(records, PRICE_RECORD_COLUMNS)[PRICE_RECORD_COLUMNS]
            records.to_csv(PRICE_RECORDS_FILE, index=False, encoding="utf-8-sig")

    # Bağlı alışveriş planlarını temizle
    shopping_sessions = read_shopping_sessions() if "read_shopping_sessions" in globals() else pd.DataFrame()
    shopping_items = read_shopping_items() if "read_shopping_items" in globals() else pd.DataFrame()

    if not shopping_sessions.empty:
        shopping_sessions = shopping_sessions[shopping_sessions["research_id"] != research_id].copy()
        write_shopping_sessions(shopping_sessions)

    if not shopping_items.empty:
        shopping_items = shopping_items[shopping_items["research_id"] != research_id].copy()
        write_shopping_items(shopping_items)

    if st.session_state.get("active_research_id", "") == research_id:
        st.session_state.active_research_id = ""
        st.session_state.active_research_mode = ""
        st.session_state.research_active = False
        st.session_state.receipt_items = []

    if st.session_state.get("compare_research_id", "") == research_id:
        st.session_state.compare_research_id = ""

    st.session_state.route_excluded_products = []
    st.session_state.route_excluded_sources = []


def load_open_research_into_state():
    if st.session_state.get("research_active", False):
        return

    sessions = read_research_sessions()

    if sessions.empty:
        return

    open_sessions = sessions[sessions["status"] == "açık"].copy()

    if open_sessions.empty:
        return

    open_sessions = open_sessions.sort_values(
        ["baslangic_tarih", "baslangic_saat"],
        ascending=[False, False]
    )

    row = open_sessions.iloc[0]

    st.session_state.active_research_id = row["research_id"]
    st.session_state.active_research_mode = row["mode"]
    st.session_state.research_active = True
    st.session_state.compare_research_id = row["research_id"]



def read_csv_smart(file_name):
    """
    Önce FiyatCep_Data_Paketi_v8.zip içindeki güncel dosyayı okur.
    Böylece klasörde eski products_master_clean.csv kalmışsa menüyü bozmaz.
    Zip yoksa aynı klasördeki CSV'ye düşer.
    """

    if os.path.exists(DATA_PACKAGE_ZIP):
        try:
            with zipfile.ZipFile(DATA_PACKAGE_ZIP) as z:
                if file_name in z.namelist():
                    with z.open(file_name) as f:
                        return pd.read_csv(f, dtype=str, encoding="utf-8-sig")
        except Exception as e:
            st.error(f"{DATA_PACKAGE_ZIP} içinden {file_name} okunamadı: {e}")
            return pd.DataFrame()

    if os.path.exists(file_name):
        try:
            return pd.read_csv(file_name, dtype=str, encoding="utf-8-sig")
        except UnicodeDecodeError:
            return pd.read_csv(file_name, dtype=str, encoding="cp1254")
        except Exception as e:
            st.error(f"{file_name} okunamadı: {e}")
            return pd.DataFrame()

    return pd.DataFrame()


@st.cache_data
def load_products():
    df = read_csv_smart(PRODUCTS_FILE)

    required = [
        "product_id",
        "sektor",
        "ana_kategori",
        "alt_kategori",
        "urun_turu",
        "marka",
        "model",
        "urun_adi",
        "birim",
        "icon",
        "photo_thumb_path",
        "photo_detail_path",
        "ui_seviye_1",
        "ui_seviye_2",
        "ui_seviye_3",
        "ui_seviye_4",
        "ui_seviye_5",
        "ui_path",
    ]

    df = ensure_columns(df, required)

    for col in required:
        df[col] = df[col].apply(clean_cell)

    # ui seviyeleri boşsa temel kolonlardan doldur.
    df["ui_seviye_1"] = df["ui_seviye_1"].where(df["ui_seviye_1"] != "", df["sektor"])
    df["ui_seviye_2"] = df["ui_seviye_2"].where(df["ui_seviye_2"] != "", df["ana_kategori"])
    df["ui_seviye_3"] = df["ui_seviye_3"].where(df["ui_seviye_3"] != "", df["alt_kategori"])
    df["ui_seviye_4"] = df["ui_seviye_4"].where(df["ui_seviye_4"] != "", df["urun_turu"])
    df["ui_seviye_5"] = df["ui_seviye_5"].where(df["ui_seviye_5"] != "", df["marka"])

    # Tamamen boş seviyeleri normalize et.
    for col in ["ui_seviye_1", "ui_seviye_2", "ui_seviye_3", "ui_seviye_4", "ui_seviye_5"]:
        df[col] = df[col].apply(clean_cell)

    df = df[df["product_id"] != ""]
    df = df[df["urun_adi"] != ""]
    df = df.drop_duplicates(subset=["product_id"], keep="first").reset_index(drop=True)

    search_cols = [
        "product_id",
        "sektor",
        "ana_kategori",
        "alt_kategori",
        "urun_turu",
        "marka",
        "model",
        "urun_adi",
        "birim",
        "ui_path",
    ]

    df["search_text"] = (
        df[search_cols]
        .fillna("")
        .astype(str)
        .agg(" ".join, axis=1)
        .apply(normalize_for_search)
    )

    return df


@st.cache_data
def load_sources():
    df = read_csv_smart(SOURCE_FILE)

    required = [
        "source_id",
        "source_type",
        "source_name",
        "related_brand",
        "sector_scope",
        "category_scope",
        "product_count",
        "is_brand_store",
        "is_user_created",
        "note",
    ]

    df = ensure_columns(df, required)

    for col in required:
        df[col] = df[col].apply(clean_cell)

    df = df[df["source_name"] != ""]
    df = df.drop_duplicates(subset=["source_id", "source_type", "source_name"], keep="first")
    df = df.reset_index(drop=True)

    return df


@st.cache_data
def load_specs():
    df = read_csv_smart(SPECS_FILE)

    if df.empty:
        df = read_csv_smart(SPECS_TEMPLATE_FILE)

    required = ["product_id", "ozellik_adi", "ozellik_degeri", "note"]
    df = ensure_columns(df, required)

    for col in required:
        df[col] = df[col].apply(clean_cell)

    df = df[
        (df["product_id"] != "") &
        (df["ozellik_adi"] != "") &
        (df["ozellik_degeri"] != "")
    ]

    return df[required].drop_duplicates().reset_index(drop=True)


@st.cache_data
def load_reference():
    df = read_csv_smart(DATA_REFERENCE_FILE)

    if df.empty:
        df = read_csv_smart(DATA_REFERENCE_TEMPLATE_FILE)

    required = [
        "product_id",
        "veri_kaynak_adi",
        "referans_fiyat",
        "para_birimi",
        "urun_linki",
        "gorsel_linki",
        "note",
    ]

    df = ensure_columns(df, required)

    for col in required:
        df[col] = df[col].apply(clean_cell)

    df = df[df["product_id"] != ""]

    return df[required].reset_index(drop=True)


products_df = load_products()
sources_df = load_sources()
specs_df = load_specs()
reference_df = load_reference()


# =========================================================
# 4. ÜRÜN / KAYNAK FONKSİYONLARI
# =========================================================

LEVEL_COLS = [
    "ui_seviye_1",
    "ui_seviye_2",
    "ui_seviye_3",
    "ui_seviye_4",
    "ui_seviye_5",
]

TREE_OPTION_ORDER = {
    "ui_seviye_1": ["Gıda", "Elektronik", "Temizlik"],
    "gida_ui_seviye_2": [
        "Meyve Sebze",
        "Kuru Gıda",
        "Şarküteri",
        "Et Tavuk Balık",
    ],
    "meyve_sebze_ui_seviye_3": [
        "Sebzeler",
        "Meyveler",
    ],
    "kuru_gida_ui_seviye_3": [
        "Kuru Bakliyat",
        "Temel Gıda",
        "Baharat",
        "Kuruyemiş",
        "İçecekler",
        "Paketli Gıda",
    ],
    "elektronik_ui_seviye_2": [
        "Telefon",
        "Bilgisayar & Tablet",
        "Beyaz Eşya & Ev Aletleri",
        "Ev & Yaşam",
        "Ağız & Diş Bakımı",
        "Saç Bakım Cihazları",
        "Tıraş & Epilasyon",
        "Kişisel Bakım",
    ],
    "bilgisayar_ui_seviye_3": [
        "Masaüstü/PC",
        "Dizüstü/Laptop",
        "Tablet",
        "Monitör",
        "Diğerleri",
    ],
}

PRODUCT_ORDER = {
    "sebzeler": [
        "domates",
        "patates",
        "salatalik",
        "taze sogan",
        "limon",
        "biber",
        "patlican",
        "pirasa",
        "havuc",
        "roka",
        "kivircik",
        "maydanoz",
        "sarmisak",
        "sarimsak",
    ],
    "meyveler": [
        "elma",
        "armut",
        "portakal",
        "ayva",
        "karpuz",
        "cilek",
        "erik",
        "kiraz",
        "nar",
    ],
}

def product_order_score(row):
    level_1 = clean_cell(st.session_state.get("level_1", ""))
    level_2 = clean_cell(st.session_state.get("level_2", ""))
    level_3 = clean_cell(st.session_state.get("level_3", ""))

    if level_1 != "Gıda" or level_2 != "Meyve Sebze":
        return 9999

    name = normalize_for_search(row.get("urun_adi", ""))

    if level_3 == "Sebzeler":
        order = PRODUCT_ORDER["sebzeler"]
    elif level_3 == "Meyveler":
        order = PRODUCT_ORDER["meyveler"]
    else:
        return 9999

    for i, key in enumerate(order):
        key_norm = normalize_for_search(key)

        if name == key_norm:
            return i * 100

        if name.startswith(key_norm + " ") or key_norm in name:
            return i * 100 + 10

        if key_norm == "taze sogan" and ("sogan taze" in name or "taze sogan" in name):
            return i * 100

    return 9999

def sort_tree_options(options, level_col):
    options = [clean_cell(x) for x in options if clean_cell(x)]

    if level_col == "ui_seviye_1":
        order = TREE_OPTION_ORDER["ui_seviye_1"]
    elif level_col == "ui_seviye_2" and st.session_state.get("level_1") == "Gıda":
        order = TREE_OPTION_ORDER["gida_ui_seviye_2"]
    elif level_col == "ui_seviye_3" and st.session_state.get("level_1") == "Gıda" and st.session_state.get("level_2") == "Meyve Sebze":
        order = TREE_OPTION_ORDER["meyve_sebze_ui_seviye_3"]
    elif level_col == "ui_seviye_3" and st.session_state.get("level_1") == "Gıda" and st.session_state.get("level_2") == "Kuru Gıda":
        order = TREE_OPTION_ORDER["kuru_gida_ui_seviye_3"]
    elif level_col == "ui_seviye_2" and st.session_state.get("level_1") == "Elektronik":
        order = TREE_OPTION_ORDER["elektronik_ui_seviye_2"]
    elif level_col == "ui_seviye_3" and st.session_state.get("level_1") == "Elektronik" and st.session_state.get("level_2") == "Bilgisayar & Tablet":
        order = TREE_OPTION_ORDER["bilgisayar_ui_seviye_3"]
    else:
        order = []

    order_map = {name: i for i, name in enumerate(order)}

    return sorted(
        options,
        key=lambda x: (order_map.get(x, 999), normalize_for_search(x))
    )


def get_filtered_products():
    df = products_df.copy()

    for i, col in enumerate(LEVEL_COLS, start=1):
        selected = clean_cell(st.session_state.get(f"level_{i}", ""))
        if selected:
            df = df[df[col] == selected]

    return df


def get_next_level_options():
    df = get_filtered_products()

    for i, col in enumerate(LEVEL_COLS, start=1):
        selected = clean_cell(st.session_state.get(f"level_{i}", ""))
        if not selected:
            options = [
                clean_cell(x)
                for x in df[col].dropna().unique()
                if clean_cell(x)
            ]
            options = sort_tree_options(options, col)
            return i, col, options

    return None, None, []


def reset_tree(from_level=1):
    for i in range(from_level, 6):
        st.session_state[f"level_{i}"] = ""

    st.session_state.product_list_limit = 12


def get_deepest_selected_level():
    deepest = 0

    for i in range(1, 6):
        if clean_cell(st.session_state.get(f"level_{i}", "")):
            deepest = i

    return deepest


def go_up_one_level():
    deepest = get_deepest_selected_level()

    if deepest <= 1:
        reset_tree(1)
    else:
        reset_tree(deepest)


def get_icon_map():
    """
    icon_map_openmoji.csv varsa ürün ikonlarını oradan okur.
    Dosya yoksa ürün adına/kategoriye göre emoji fallback üretir.
    """
    if not os.path.exists(ICON_MAP_FILE):
        return {}

    try:
        df = pd.read_csv(ICON_MAP_FILE, dtype=str, encoding="utf-8-sig").fillna("")
    except UnicodeDecodeError:
        df = pd.read_csv(ICON_MAP_FILE, dtype=str, encoding="cp1254").fillna("")
    except Exception:
        return {}

    if "product_id" not in df.columns:
        return {}

    records = {}
    for _, row in df.iterrows():
        pid = clean_cell(row.get("product_id", ""))
        if not pid:
            continue
        records[pid] = {
            "icon_file": clean_cell(row.get("icon_file", "")),
            "emoji": clean_cell(row.get("emoji_fallback", "")),
            "icon_id": clean_cell(row.get("icon_id", "")),
        }

    return records


@st.cache_data(show_spinner=False)
def cached_icon_map():
    return get_icon_map()


def contains_keyword(normalized_text, normalized_keyword):
    """
    Kısa kelimeleri yanlış yakalamamak için güvenli eşleştirme.
    Örn: 'et' kelimesi 'market' veya 'tablet' içinde geçiyor diye et ikonu seçilmez.
    """
    normalized_text = clean_cell(normalized_text)
    normalized_keyword = clean_cell(normalized_keyword)

    if not normalized_text or not normalized_keyword:
        return False

    text_with_space = f" {normalized_text} "
    keyword_with_space = f" {normalized_keyword} "

    # Birden fazla kelimeli anahtarlar phrase olarak aranır.
    if " " in normalized_keyword:
        return keyword_with_space in text_with_space

    # Tek kelimeler token olarak aranır.
    return normalized_keyword in normalized_text.split()


def read_icon_rules():
    if not os.path.exists(ICON_RULES_FILE):
        return []

    try:
        df = pd.read_csv(ICON_RULES_FILE, dtype=str, encoding="utf-8-sig").fillna("")
    except UnicodeDecodeError:
        df = pd.read_csv(ICON_RULES_FILE, dtype=str, encoding="cp1254").fillna("")
    except Exception:
        return []

    df = ensure_columns(df, ["keyword", "icon_group", "emoji", "openmoji_codepoint", "priority", "note"])

    records = []
    for _, row in df.iterrows():
        keyword = clean_cell(row.get("keyword", ""))
        if not keyword:
            continue

        priority_text = clean_cell(row.get("priority", ""))

        try:
            priority = int(priority_text)
        except Exception:
            priority = 999

        records.append({
            "keyword": keyword,
            "keyword_norm": normalize_for_search(keyword),
            "icon_group": clean_cell(row.get("icon_group", "")),
            "emoji": clean_cell(row.get("emoji", "")),
            "openmoji_codepoint": clean_cell(row.get("openmoji_codepoint", "")).upper(),
            "priority": priority,
            "note": clean_cell(row.get("note", "")),
        })

    records.sort(key=lambda item: (item["priority"], -len(item["keyword_norm"])))
    return records


@st.cache_data(show_spinner=False)
def cached_icon_rules():
    return read_icon_rules()


def match_icon_rule(text):
    n = normalize_for_search(text)

    if not n:
        return {}

    for rule in cached_icon_rules():
        if contains_keyword(n, rule["keyword_norm"]):
            return rule

    return {}


def icon_file_candidates_from_codepoint(codepoint):
    codepoint = clean_cell(codepoint).upper()

    if not codepoint:
        return []

    return [
        os.path.join(ICON_DIR, f"{codepoint}.svg"),
        os.path.join(ICON_DIR, f"{codepoint.lower()}.svg"),
    ]


def render_svg_icon_from_file(path, size=58):
    try:
        with open(path, "rb") as f:
            encoded = base64.b64encode(f.read()).decode("utf-8")
        return f'<img src="data:image/svg+xml;base64,{encoded}" style="width:{size}px;height:{size}px;object-fit:contain;display:block;margin:0 auto 6px auto;" />'
    except Exception:
        return ""


def infer_icon_emoji(text):
    """
    Fallback emoji eşleştirme.
    Asıl karar icon_rules.csv üstünden verilir.
    """
    n = normalize_for_search(text)

    rules = [
        (["cupra", "çupra", "levrek", "somon", "hamsi", "palamut", "lufer", "lüfer", "alabalik", "alabalık", "uskumru", "sardalya", "balik", "fish"], "🐟"),
        (["dana", "kuzu", "koyun", "kıyma", "kiyma", "bonfile", "biftek", "antrikot", "incik", "pirzola", "kusbasi", "kuşbaşı", "et"], "🥩"),
        (["tavuk", "chicken", "but", "kanat", "gogus", "göğüs"], "🍗"),
        (["domates", "tomato"], "🍅"),
        (["patates", "potato"], "🥔"),
        (["salatalik", "hiyar", "cucumber"], "🥒"),
        (["taze sogan", "sogan", "onion"], "🧅"),
        (["limon", "lemon"], "🍋"),
        (["biber", "pepper", "kapya", "carliston", "dolmalik"], "🌶️"),
        (["patlican", "eggplant"], "🍆"),
        (["pirasa", "leek"], "🥬"),
        (["havuc", "carrot"], "🥕"),
        (["roka", "kivircik", "marul", "lettuce"], "🥬"),
        (["maydanoz", "parsley", "dereotu", "tere", "nane", "kekik"], "🌿"),
        (["sarimsak", "sarmisak", "garlic"], "🧄"),
        (["elma", "apple"], "🍎"),
        (["armut", "pear"], "🍐"),
        (["portakal", "orange", "mandalina"], "🍊"),
        (["karpuz", "watermelon"], "🍉"),
        (["cilek", "strawberry"], "🍓"),
        (["erik", "plum"], "🟣"),
        (["kiraz", "cherry"], "🍒"),
        (["nar", "pomegranate"], "🔴"),
        (["ayva"], "🍐"),
        (["sut", "milk"], "🥛"),
        (["yogurt", "yoğurt"], "🥛"),
        (["peynir", "cheese"], "🧀"),
        (["yumurta", "egg"], "🥚"),
        (["ekmek", "bread"], "🍞"),
        (["makarna", "pasta"], "🍝"),
        (["pirinc", "rice"], "🍚"),
        (["bulgur", "mercimek", "fasulye", "nohut", "bakliyat"], "🫘"),
        (["baharat", "kimyon", "pul biber"], "🧂"),
        (["cay", "tea"], "🍵"),
        (["kahve", "coffee"], "☕"),
        (["su"], "💧"),
        (["telefon", "iphone", "samsung", "xiaomi", "tecno", "vivo", "smartphone"], "📱"),
        (["laptop", "notebook", "macbook", "dizustu", "acer", "asus", "dell", "lenovo", "monster", "msi", "hp"], "💻"),
        (["tablet"], "📱"),
        (["monitor"], "🖥️"),
        (["buzdolabi", "buzdolabı"], "🧊"),
        (["camasir makinesi", "çamaşır makinesi"], "🧺"),
        (["bulasik makinesi", "bulaşık makinesi"], "🍽️"),
        (["firin", "fırın", "mikrodalga"], "🔥"),
        (["supurge", "süpürge", "vacuum", "dreame"], "🧹"),
        (["utu", "ütü"], "♨️"),
        (["airfryer", "fritoz"], "🍟"),
        (["mikser", "blender", "rondo", "mutfak robotu", "mutfak sefi"], "🥣"),
        (["kettle", "su isiticisi", "cay makinesi"], "☕"),
        (["dis fircasi", "diş fırçası", "agiz", "ağız"], "🪥"),
        (["tras", "tıraş", "epilasyon"], "🪒"),
        (["sampuan", "şampuan", "sabun"], "🧴"),
        (["deterjan", "temizleyici", "camasir suyu", "çamaşır suyu", "yumusatici"], "🧴"),
        (["tuvalet kagidi", "kağıt havlu", "pecete"], "🧻"),
        (["akaryakit", "benzin", "motorin", "lpg"], "⛽"),
    ]

    for keys, emoji in rules:
        for key in keys:
            if contains_keyword(n, normalize_for_search(key)):
                return emoji

    if contains_keyword(n, "gida") or contains_keyword(n, "meyve") or contains_keyword(n, "sebze"):
        return "🛒"
    if contains_keyword(n, "telefon"):
        return "📱"
    if contains_keyword(n, "bilgisayar") or contains_keyword(n, "laptop") or contains_keyword(n, "notebook"):
        return "💻"
    if contains_keyword(n, "elektronik"):
        return "🔌"
    if contains_keyword(n, "temizlik"):
        return "🧽"

    return "🛒"


def get_product_icon_context(product_id="", text=""):
    """
    İkon eşleşmesinde sadece görünen ürün adını değil,
    ürünün kategori/marka/model bilgisini de kullanır.
    Böylece Acer/Apple gibi elektronik ürünler eski icon_map yüzünden et ikonuna düşmez.
    """
    parts = [clean_cell(text)]
    product_id = clean_cell(product_id)

    if product_id and not products_df.empty:
        matched = products_df[products_df["product_id"].astype(str) == product_id]

        if not matched.empty:
            row = matched.iloc[0]
            for col in [
                "urun_adi", "marka", "model", "sektor", "ana_kategori",
                "alt_kategori", "urun_turu", "ui_path",
                "ui_seviye_1", "ui_seviye_2", "ui_seviye_3", "ui_seviye_4", "ui_seviye_5"
            ]:
                if col in row.index:
                    parts.append(clean_cell(row.get(col, "")))

    return compact_join(parts, sep=" ")


def get_product_icon_html(product_id="", text="", size=58):
    full_text = get_product_icon_context(product_id, text)

    # 1) Öncelik icon_rules.csv: yanlış otomatik eşleşmeleri ezsin.
    rule = match_icon_rule(full_text)

    if rule:
        for path in icon_file_candidates_from_codepoint(rule.get("openmoji_codepoint", "")):
            if os.path.exists(path):
                svg = render_svg_icon_from_file(path, size=size)
                if svg:
                    return svg

        if clean_cell(rule.get("emoji", "")):
            return f'<div style="font-size:{size}px; line-height:1; text-align:center; margin-bottom:6px;">{rule["emoji"]}</div>'

    # 2) Eski icon_map bazı ürünleri yanlış eşleştirmiş olabilir.
    # Eğer ürünün kategorisi/markası netse icon_map yerine canlı kural/fallback kullan.
    n = normalize_for_search(full_text)
    has_clear_category = any(
        contains_keyword(n, normalize_for_search(k))
        for k in [
            "elektronik", "telefon", "bilgisayar", "tablet", "laptop", "notebook",
            "macbook", "monitor", "acer", "asus", "dell", "hp", "lenovo", "msi",
            "monster", "apple", "iphone", "samsung", "xiaomi", "tecno", "vivo",
            "gida", "meyve", "sebze", "temizlik"
        ]
    )

    if not has_clear_category:
        icon_map = cached_icon_map()
        record = icon_map.get(clean_cell(product_id), {})

        icon_file = clean_cell(record.get("icon_file", ""))

        if icon_file:
            candidates = [
                icon_file,
                os.path.join(ICON_DIR, icon_file),
                os.path.join(ICON_DIR, os.path.basename(icon_file)),
            ]

            for path in candidates:
                if os.path.exists(path):
                    svg = render_svg_icon_from_file(path, size=size)
                    if svg:
                        return svg

        emoji = clean_cell(record.get("emoji", "")) or infer_icon_emoji(full_text)
    else:
        emoji = infer_icon_emoji(full_text)

    return f'<div style="font-size:{size}px; line-height:1; text-align:center; margin-bottom:6px;">{emoji}</div>'


def get_product_icon_emoji(product_id="", text=""):
    full_text = get_product_icon_context(product_id, text)

    rule = match_icon_rule(full_text)

    if rule and clean_cell(rule.get("emoji", "")):
        return rule["emoji"]

    n = normalize_for_search(full_text)
    has_clear_category = any(
        contains_keyword(n, normalize_for_search(k))
        for k in [
            "elektronik", "telefon", "bilgisayar", "tablet", "laptop", "notebook",
            "macbook", "monitor", "acer", "asus", "dell", "hp", "lenovo", "msi",
            "monster", "apple", "iphone", "samsung", "xiaomi", "tecno", "vivo",
            "gida", "meyve", "sebze", "temizlik"
        ]
    )

    if has_clear_category:
        return infer_icon_emoji(full_text)

    icon_map = cached_icon_map()
    record = icon_map.get(clean_cell(product_id), {})
    return clean_cell(record.get("emoji", "")) or infer_icon_emoji(full_text)




def get_specs_preview(product_id, max_items=4):
    if specs_df.empty:
        return ""

    subset = specs_df[specs_df["product_id"] == product_id]

    if subset.empty:
        return ""

    items = []
    for _, row in subset.head(max_items).iterrows():
        items.append(f"{row['ozellik_adi']}: {row['ozellik_degeri']}")

    return " • ".join(items)


def get_reference_preview(product_id):
    if reference_df.empty:
        return ""

    subset = reference_df[reference_df["product_id"] == product_id]

    if subset.empty:
        return ""

    first = subset.iloc[0]
    kaynak = clean_cell(first.get("veri_kaynak_adi", ""))
    fiyat = clean_cell(first.get("referans_fiyat", ""))
    para = clean_cell(first.get("para_birimi", "")) or "₺"

    return compact_join([kaynak, f"{fiyat} {para}" if fiyat else ""], sep=" / ")


def source_label(row):
    return compact_join([
        row.get("source_name", ""),
        row.get("source_type", ""),
    ], sep=" • ")


def select_source_from_row(row):
    st.session_state.source_id = clean_cell(row.get("source_id", ""))
    st.session_state.source_type = clean_cell(row.get("source_type", ""))
    st.session_state.source_name = clean_cell(row.get("source_name", ""))
    st.session_state.source_auto_selected = False
    st.session_state.step = "product_tree"
    reset_tree(1)


def select_manual_source(source_type, source_name):
    st.session_state.source_id = "USER_" + normalize_for_search(source_name).replace(" ", "_")[:50]
    st.session_state.source_type = clean_cell(source_type) or "Kullanıcı Girdisi"
    st.session_state.source_name = clean_cell(source_name)
    st.session_state.source_auto_selected = False
    st.session_state.step = "product_tree"
    reset_tree(1)



def build_receipt_item_from_product_row(product_row):
    product_id = clean_cell(product_row.get("product_id", ""))

    return {
        "line_id": "L" + str(len(st.session_state.receipt_items) + 1).zfill(3),
        "product_id": product_id,
        "urun_adi": clean_cell(product_row.get("urun_adi", "")),
        "marka": clean_cell(product_row.get("marka", "")),
        "model": clean_cell(product_row.get("model", "")),
        "varyant": "",
        "birim": clean_cell(product_row.get("birim", "")) or "Adet",
        "title": format_product_title(product_row),
        "path": format_product_subtitle(product_row),
        "sektor": clean_cell(product_row.get("sektor", "")),
        "ana_kategori": clean_cell(product_row.get("ana_kategori", "")),
        "alt_kategori": clean_cell(product_row.get("alt_kategori", "")),
        "urun_turu": clean_cell(product_row.get("urun_turu", "")),
        "fiyat": "",
        "not": "",
    }


def get_last_receipt_lines_for_active_research():
    """
    Aktif fiyat araştırmasındaki son kaydedilen fişin ürün satırlarını getirir.
    Amaç: yeni konum/kaynak için aynı ürün listesini tek butonla tekrar fişe almak.
    Fiyat ve kaynak kopyalanmaz; sadece ürün listesi kopyalanır.
    """
    saved_df = read_saved_price_records()

    if saved_df.empty:
        return pd.DataFrame()

    research_id = clean_cell(st.session_state.get("active_research_id", ""))

    if research_id and "research_id" in saved_df.columns:
        saved_df = saved_df[saved_df["research_id"] == research_id].copy()

    if saved_df.empty:
        return pd.DataFrame()

    saved_df = saved_df[saved_df["receipt_id"] != ""].copy()

    if saved_df.empty:
        return pd.DataFrame()

    latest_receipt_id = (
        saved_df
        .sort_values(["tarih", "saat"], ascending=[False, False])
        .iloc[0]["receipt_id"]
    )

    latest = saved_df[saved_df["receipt_id"] == latest_receipt_id].copy()
    latest = latest.drop_duplicates(subset=["product_id"], keep="first")

    return latest


def import_last_receipt_product_list():
    last_lines = get_last_receipt_lines_for_active_research()

    if last_lines.empty:
        st.warning("Bu araştırmada kopyalanacak önceki fiş bulunamadı.")
        return

    added_count = 0
    skipped_count = 0

    existing_ids = {
        clean_cell(item.get("product_id", ""))
        for item in st.session_state.receipt_items
    }

    for _, line in last_lines.iterrows():
        product_id = clean_cell(line.get("product_id", ""))

        if not product_id or product_id in existing_ids:
            skipped_count += 1
            continue

        matched = products_df[products_df["product_id"] == product_id]

        if not matched.empty:
            product_row = matched.iloc[0]
            item = build_receipt_item_from_product_row(product_row)
        else:
            # Ürün artık master datada bulunamazsa, fiyat kaydındaki temel bilgilerle yine de ekle.
            fallback_row = {
                "product_id": product_id,
                "urun_adi": clean_cell(line.get("urun_adi", "")),
                "marka": clean_cell(line.get("marka", "")),
                "model": clean_cell(line.get("model", "")),
                "birim": clean_cell(line.get("birim", "")) or "Adet",
                "sektor": "",
                "ana_kategori": "",
                "alt_kategori": "",
                "urun_turu": "",
            }
            item = build_receipt_item_from_product_row(fallback_row)

        st.session_state.receipt_items.append(item)
        existing_ids.add(product_id)
        added_count += 1

    # Önceki kaynak kopyalanmasın; yeni lokasyon/kaynak için yeniden önerilsin.
    st.session_state.source_id = ""
    st.session_state.source_type = ""
    st.session_state.source_name = ""
    st.session_state.source_auto_selected = False

    st.success(f"Son fişteki {added_count} ürün listeye eklendi.")

    if skipped_count:
        st.caption(f"{skipped_count} ürün zaten listede olduğu için atlandı.")



def add_to_receipt(product_row):
    product_id = clean_cell(product_row.get("product_id", ""))

    already = [
        item for item in st.session_state.receipt_items
        if item["product_id"] == product_id
    ]

    if already:
        st.toast("Bu ürün fişte zaten var.")
        return

    item = build_receipt_item_from_product_row(product_row)

    st.session_state.receipt_items.append(item)

    if st.session_state.get("source_auto_selected", False):
        st.session_state.source_id = ""
        st.session_state.source_type = ""
        st.session_state.source_name = ""

    st.toast("Fişe eklendi.")


def remove_from_receipt(index):
    if 0 <= index < len(st.session_state.receipt_items):
        st.session_state.receipt_items.pop(index)

    if st.session_state.get("source_auto_selected", False):
        st.session_state.source_id = ""
        st.session_state.source_type = ""
        st.session_state.source_name = ""

    for i, item in enumerate(st.session_state.receipt_items, start=1):
        item["line_id"] = "L" + str(i).zfill(3)


def update_receipt_prices_from_inputs():
    for i, item in enumerate(st.session_state.receipt_items):
        price_key = f"receipt_price_{i}_{item['product_id']}"
        note_key = f"receipt_note_{i}_{item['product_id']}"

        item["fiyat"] = clean_cell(st.session_state.get(price_key, item.get("fiyat", "")))
        item["not"] = clean_cell(st.session_state.get(note_key, item.get("not", "")))


def save_receipt():
    update_receipt_prices_from_inputs()

    if not st.session_state.get("research_active", False) or not st.session_state.get("active_research_id", ""):
        st.error("Fiş kaydetmeden önce Fiyat Araştırması Başlat.")
        return

    if not st.session_state.location_confirmed:
        st.error("Bu yeni fiş için konumu güncellemen gerekiyor.")
        return

    if not st.session_state.source_name:
        st.error("Kaydetmeden önce önerilen fiş kaynağını onayla, değiştir ya da elle yaz.")
        return

    if not st.session_state.receipt_items:
        st.error("Fişte ürün yok.")
        return

    valid_items = []
    invalid_items = []

    for item in st.session_state.receipt_items:
        price = parse_price(item.get("fiyat", ""))
        if price is None:
            invalid_items.append(item)
        else:
            item_copy = item.copy()
            item_copy["fiyat"] = price
            valid_items.append(item_copy)

    if invalid_items:
        st.error("Fiyatı boş veya hatalı ürün var. Kaydetmeden önce tüm fiyatları gir.")
        return

    receipt_id = "R" + datetime.now().strftime("%Y%m%d%H%M%S") + "_" + uuid.uuid4().hex[:6]
    tarih, saat = get_today_strings()

    header_row = {
        "receipt_id": receipt_id,
        "research_id": st.session_state.active_research_id,
        "tarih": tarih,
        "saat": saat,
        "source_id": st.session_state.source_id,
        "source_type": st.session_state.source_type,
        "source_name": st.session_state.source_name,
        "konum_lat": st.session_state.location_lat,
        "konum_lon": st.session_state.location_lon,
        "konum_dogrulandi": st.session_state.location_confirmed,
        "toplam_kalem": len(valid_items),
        "not": st.session_state.receipt_note,
    }

    line_rows = []

    for item in valid_items:
        line_rows.append({
            "receipt_id": receipt_id,
            "research_id": st.session_state.active_research_id,
            "line_id": item["line_id"],
            "tarih": tarih,
            "saat": saat,
            "source_id": st.session_state.source_id,
            "source_type": st.session_state.source_type,
            "source_name": st.session_state.source_name,
            "product_id": item["product_id"],
            "urun_adi": item["urun_adi"],
            "marka": item["marka"],
            "model": item["model"],
            "varyant": item["varyant"],
            "birim": item["birim"],
            "fiyat": item["fiyat"],
            "konum_lat": st.session_state.location_lat,
            "konum_lon": st.session_state.location_lon,
            "not": item.get("not", ""),
        })

    append_csv(RECEIPT_HEADER_FILE, [header_row], RECEIPT_HEADER_COLUMNS)
    append_csv(PRICE_RECORDS_FILE, line_rows, PRICE_RECORD_COLUMNS)

    st.session_state.last_save_status = f"Fiş kaydedildi: {receipt_id}"
    st.session_state.compare_receipt_id = receipt_id
    st.session_state.compare_research_id = st.session_state.active_research_id
    st.session_state.receipt_items = []
    st.session_state.clear_receipt_inputs_next_run = True

    # Yeni fişte kaynak yeniden seçilsin; konum ise kullanıcı isterse fiş üstünden değiştirir.
    st.session_state.source_id = ""
    st.session_state.source_type = ""
    st.session_state.source_name = ""
    st.session_state.source_auto_selected = False
    st.session_state.needs_location_update = False

    st.success(st.session_state.last_save_status)


# =========================================================
# 5. ARAMA
# =========================================================

def search_products(query, limit=40):
    query_norm = normalize_for_search(query)

    if len(query_norm) < 3 or products_df.empty:
        return pd.DataFrame(columns=products_df.columns)

    tokens = query_norm.split()

    result = products_df[
        products_df["search_text"].apply(
            lambda text: all(token in text for token in tokens)
        )
    ].copy()

    if result.empty and len(tokens) > 1:
        result = products_df[
            products_df["search_text"].apply(
                lambda text: any(token in text for token in tokens)
            )
        ].copy()

    if result.empty:
        return result

    def score_row(row):
        main_text = normalize_for_search(compact_join([
            row.get("marka", ""),
            row.get("model", ""),
            row.get("urun_adi", ""),
        ]))

        path_text = normalize_for_search(row.get("ui_path", ""))

        score = 0

        if query_norm in main_text:
            score += 100

        if query_norm in path_text:
            score += 50

        for token in tokens:
            if token in main_text:
                score += 20
            if token in path_text:
                score += 8

        return score

    result["search_score"] = result.apply(score_row, axis=1)
    result = result.sort_values("search_score", ascending=False).head(limit)

    return result


# =========================================================
# 6. CSS
# =========================================================

st.markdown("""
<style>
.main-card {
    border: 1px solid #e2e8f0;
    border-radius: 18px;
    padding: 14px;
    background: #ffffff;
    margin-bottom: 12px;
}

.small-muted {
    color: #64748b;
    font-size: 12px;
}

.product-title {
    color: #0f172a;
    font-size: 15px;
    font-weight: 800;
}

.product-path {
    color: #64748b;
    font-size: 12px;
}

.receipt-box {
    border: 2px solid #0f172a;
    border-radius: 18px;
    padding: 14px;
    background: #f8fafc;
    margin-bottom: 16px;
}

.receipt-item {
    border-bottom: 1px solid #e2e8f0;
    padding: 8px 0;
}

.stButton>button {
    min-height: 54px;
    border-radius: 12px;
    font-weight: 800;
    white-space: normal;
    line-height: 1.15;
    word-break: break-word;
    font-size: 15px;
}

div[data-testid="stTextInput"] input {
    min-height: 42px;
}
.fixed-bottom-nav {
    position: fixed;
    bottom: 0;
    left: 0;
    width: 100%;
    background: #ffffff;
    border-top: 1px solid #cbd5e1;
    padding: 10px 12px;
    z-index: 9999;
    box-shadow: 0 -4px 14px rgba(15, 23, 42, 0.12);
}
.bottom-spacer {
    height: 86px;
}
</style>
""", unsafe_allow_html=True)


# =========================================================
# 7. SESSION STATE
# =========================================================

def init_state():
    defaults = {
        "step": "location",
        "location_lat": "",
        "location_lon": "",
        "location_confirmed": False,

        "source_id": "",
        "source_type": "",
        "source_name": "",
        "source_auto_selected": False,

        "receipt_items": [],
        "receipt_note": "",
        "last_save_status": "",
        "compare_receipt_id": "",

        "research_active": False,
        "active_research_id": "",
        "active_research_mode": "",
        "compare_research_id": "",
        "research_start_mode": "Bugün alacağım",
        "research_history_index": 0,
        "needs_location_update": False,
        "shopping_checked": {},
        "current_shopping_id": "",
        "current_user_list_id": "",
        "route_excluded_products": [],
        "route_excluded_sources": [],

        "product_list_limit": 12,
        "search_query": "",
        "search_limit": 8,
        "clear_search_query_next_run": False,
        "clear_receipt_inputs_next_run": False,
        "source_group_filter": "Tümü",
        "price_entry_index": None,
        "price_entry_value": "",
    }

    for i in range(1, 6):
        defaults[f"level_{i}"] = ""

    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


init_state()
load_open_research_into_state()


# =========================================================
# 8. ÜST BİLGİ
# =========================================================

st.title("🧾 FiyatCep")
st.caption("Data paketi: v9 + araştırma oturumu v1")

if st.session_state.get("research_active", False):
    st.success(f"Açık fiyat araştırması: {st.session_state.active_research_mode}")
else:
    st.caption("Açık fiyat araştırması yok.")

if st.session_state.source_name:
    st.caption(
        f"Fiş kaynağı: {st.session_state.source_name}"
        + (f" / {st.session_state.source_type}" if st.session_state.source_type else "")
    )
else:
    st.caption("Önce ürünleri seç. Fişi kaydetmeden önce fiyat kaynağını seçeceksin.")

if st.session_state.last_save_status:
    st.success(st.session_state.last_save_status)


# =========================================================
# 9. FİŞ PANELİ
# =========================================================

def apply_auto_source_if_needed():
    if not st.session_state.receipt_items:
        return

    if st.session_state.source_name and not st.session_state.get("source_auto_selected", False):
        return

    suggestion = get_best_source_suggestion()

    if suggestion is None:
        return

    suggested_id = clean_cell(suggestion.get("source_id", ""))

    if st.session_state.source_id == suggested_id and st.session_state.source_name:
        return

    st.session_state.source_id = suggested_id
    st.session_state.source_type = clean_cell(suggestion.get("source_type", ""))
    st.session_state.source_name = clean_cell(suggestion.get("source_name", ""))
    st.session_state.source_auto_selected = True



def open_price_entry(index):
    if index < 0 or index >= len(st.session_state.receipt_items):
        return

    item = st.session_state.receipt_items[index]
    st.session_state.price_entry_index = index
    st.session_state.price_entry_value = clean_cell(item.get("fiyat", ""))
    st.session_state.step = "price_entry"


def render_price_entry_screen():
    index = st.session_state.get("price_entry_index", None)

    if index is None or index < 0 or index >= len(st.session_state.receipt_items):
        st.warning("Fiyat girilecek ürün bulunamadı.")
        if st.button("⬅️ Fişe Dön", use_container_width=True):
            st.session_state.step = "product_tree"
            st.rerun()
        return

    item = st.session_state.receipt_items[index]
    title = clean_cell(item.get("title", ""))

    st.subheader("💰 Fiyat Gir")
    st.markdown(f"### {title}")

    value = clean_cell(st.session_state.get("price_entry_value", ""))
    display_value = value if value else "0"

    st.markdown(
        f"""
        <div style="
            border:2px solid #0f172a;
            border-radius:18px;
            padding:18px;
            text-align:right;
            font-size:42px;
            font-weight:900;
            margin:12px 0;
            background:#f8fafc;
        ">
            {display_value} ₺
        </div>
        """,
        unsafe_allow_html=True
    )

    def press(val):
        current = clean_cell(st.session_state.get("price_entry_value", ""))

        if val == "C":
            current = ""
        elif val == "⌫":
            current = current[:-1]
        elif val == ",":
            if "," not in current and "." not in current:
                current = current + ","
        else:
            current = current + val

        st.session_state.price_entry_value = current

    keypad = [
        ["1", "2", "3"],
        ["4", "5", "6"],
        ["7", "8", "9"],
        [",", "0", "⌫"],
    ]

    for r, row in enumerate(keypad):
        cols = st.columns(3)
        for c, val in enumerate(row):
            if cols[c].button(val, key=f"keypad_{r}_{c}_{val}", use_container_width=True):
                press(val)
                st.rerun()

    c1, c2, c3 = st.columns(3)

    if c1.button("Temizle", use_container_width=True):
        press("C")
        st.rerun()

    if c2.button("İptal", use_container_width=True):
        st.session_state.step = "product_tree"
        st.rerun()

    if c3.button("Kaydet", use_container_width=True, type="primary"):
        price = parse_price(st.session_state.price_entry_value)

        if price is None:
            st.error("Geçerli bir fiyat gir.")
            return

        st.session_state.receipt_items[index]["fiyat"] = str(price).replace(".", ",")
        st.session_state.price_entry_index = None
        st.session_state.price_entry_value = ""
        st.session_state.step = "product_tree"
        st.rerun()



def render_receipt_panel():
    st.markdown('<div class="receipt-box">', unsafe_allow_html=True)

    st.subheader("Fiş / Adisyon")

    # Konum fişin üstünde sabit görünsün; zorunlu güncelleme yerine kullanıcı istediğinde değiştirsin.
    loc1, loc2 = st.columns([3, 1])

    if st.session_state.location_confirmed:
        loc_text = compact_join([
            st.session_state.get("location_lat", ""),
            st.session_state.get("location_lon", "")
        ], sep=", ")
        loc1.markdown(
            f"""
            <div style="border:1px solid #cbd5e1; border-radius:14px; padding:10px; background:#eef2ff; margin-bottom:8px;">
                <div style="font-size:12px; color:#475569; font-weight:800;">📍 Fiş Konumu</div>
                <div style="font-size:16px; font-weight:900; color:#0f172a;">{loc_text or "Konum doğrulandı"}</div>
            </div>
            """,
            unsafe_allow_html=True
        )
    else:
        loc1.markdown(
            """
            <div style="border:1px solid #fecaca; border-radius:14px; padding:10px; background:#fef2f2; margin-bottom:8px;">
                <div style="font-size:12px; color:#991b1b; font-weight:800;">📍 Fiş Konumu</div>
                <div style="font-size:16px; font-weight:900; color:#991b1b;">Konum doğrulanmadı</div>
            </div>
            """,
            unsafe_allow_html=True
        )

    if loc2.button("Konumu Değiştir", use_container_width=True, key="receipt_update_location"):
        st.session_state.step = "location"
        st.rerun()

    # Streamlit kuralı:
    # Bir widget aynı çalıştırmada oluşturulduktan sonra onun session_state key'i değiştirilemez.
    # Bu yüzden fiş notu ve fiyat input temizliği, widgetlar oluşturulmadan önce yapılır.
    if st.session_state.get("clear_receipt_inputs_next_run", False):
        st.session_state.receipt_note = ""

        for key in list(st.session_state.keys()):
            if key.startswith("receipt_price_") or key.startswith("receipt_note_"):
                del st.session_state[key]

        st.session_state.clear_receipt_inputs_next_run = False

    apply_auto_source_if_needed()

    if not st.session_state.source_name:
        st.markdown(
            """
            <div style="border:1px solid #fde68a; border-radius:14px; padding:10px; background:#fffbeb; margin-bottom:10px;">
                <div style="font-size:12px; color:#92400e; font-weight:800;">🏪 Fiş Kaynağı</div>
                <div style="font-size:16px; font-weight:900; color:#92400e;">Kaynak henüz seçilmedi</div>
                <div style="font-size:11px; color:#92400e;">Ürün ekleyince otomatik önerilir; istersen elle değiştir.</div>
            </div>
            """,
            unsafe_allow_html=True
        )
    else:
        csrc1, csrc2 = st.columns([3, 1])
        auto_note = "Otomatik öneri" if st.session_state.get("source_auto_selected", False) else "Seçili kaynak"
        csrc1.markdown(
            f"""
            <div style="border:1px solid #bbf7d0; border-radius:14px; padding:10px; background:#f0fdf4; margin-bottom:10px;">
                <div style="font-size:12px; color:#166534; font-weight:800;">🏪 Fiş Kaynağı</div>
                <div style="font-size:20px; font-weight:900; color:#052e16;">{st.session_state.source_name}</div>
                <div style="font-size:12px; color:#166534;">{st.session_state.source_type} • {auto_note}</div>
            </div>
            """,
            unsafe_allow_html=True
        )
        if csrc2.button("Kaynağı Değiştir", key="change_source_from_receipt", use_container_width=True):
            st.session_state.step = "source_smart"
            st.rerun()

    if not st.session_state.receipt_items:
        st.info("Fişe henüz ürün eklenmedi.")

        latest_list_id = get_latest_user_shopping_list_id()

        if latest_list_id:
            lists = read_user_lists()
            selected = lists[lists["list_id"] == latest_list_id].copy()
            list_name = "Alışveriş listesi"

            if not selected.empty:
                list_name = clean_cell(selected.iloc[0].get("ad", "")) or list_name

            st.caption("Hazırladığın listeyle fiyat girmek istiyorsan:")
            if st.button(f"📋 Alışveriş listesini getir: {list_name}", use_container_width=True, key="import_latest_user_list"):
                import_user_list_to_receipt(latest_list_id)
                st.rerun()

            if st.button("📋 Başka liste seç", use_container_width=True, key="choose_user_list_for_receipt"):
                st.session_state.step = "user_lists"
                st.rerun()

        last_lines = get_last_receipt_lines_for_active_research()

        if not last_lines.empty:
            st.caption("Yeni konum/kaynak için aynı ürün listesini tekrar gireceksen:")
            if st.button("📋 Son fişteki ürün listesini ekle", use_container_width=True, key="import_last_receipt_items"):
                import_last_receipt_product_list()
                st.rerun()

    else:
        update_receipt_prices_from_inputs()

        total = 0.0
        all_valid = True

        rows = list(enumerate(st.session_state.receipt_items))
        products_per_row = 4

        for start_idx in range(0, len(rows), products_per_row):
            chunk = rows[start_idx:start_idx + products_per_row]
            cols = st.columns(products_per_row)

            for col_idx, (i, item) in enumerate(chunk):
                with cols[col_idx]:
                    price_key = f"receipt_price_{i}_{item['product_id']}"
                    current_price = clean_cell(item.get("fiyat", ""))

                    if price_key in st.session_state:
                        current_price = clean_cell(st.session_state.get(price_key, current_price))
                        item["fiyat"] = current_price

                    parsed = parse_price(current_price)

                    if parsed is None:
                        all_valid = False
                        price_text = "Fiyat gir"
                        price_color = "#dc2626"
                    else:
                        total += parsed
                        price_text = f"{format_price(str(parsed))} ₺"
                        price_color = "#0f172a"

                    icon_html = get_product_icon_html(item["product_id"], f"{item['title']} {item['path']}", size=48)

                    st.markdown(
                        f"""
                        <div style="
                            border:1px solid #cbd5e1;
                            border-radius:14px;
                            padding:8px;
                            min-height:178px;
                            background:#ffffff;
                            margin-bottom:6px;
                        ">
                            {icon_html}
                            <div style="font-weight:900; font-size:13px; line-height:1.18; color:#0f172a;">{i + 1}. {item['title']}</div>
                            <div style="font-size:10px; color:#64748b; margin-top:5px;">{item['birim']} • {item['path']}</div>
                            <div style="font-size:18px; color:{price_color}; font-weight:900; margin-top:8px;">{price_text}</div>
                        </div>
                        """,
                        unsafe_allow_html=True
                    )

                    if st.button(
                        "💰 Fiyat Gir",
                        key=safe_key("open_price_entry", item["product_id"], i),
                        use_container_width=True
                    ):
                        open_price_entry(i)
                        st.rerun()

                    if st.button(
                        "Sil",
                        key=safe_key("remove_receipt", item["product_id"], i),
                        use_container_width=True
                    ):
                        remove_from_receipt(i)
                        st.rerun()

        st.markdown(f"### Toplam: {format_price(str(total))} ₺")

        st.text_input(
            "Fiş notu",
            key="receipt_note",
            placeholder="Opsiyonel fiş notu",
        )

        s1, s2, s3 = st.columns(3)

        if s1.button("✅ FİŞİ KAYDET", use_container_width=True, type="primary"):
            save_receipt()
            st.rerun()

        if s2.button("📊 En Ucuz / Rota", use_container_width=True):
            st.session_state.step = "compare_prices"
            st.rerun()

        if s3.button("🧹 Temizle", use_container_width=True):
            st.session_state.receipt_items = []
            st.session_state.clear_receipt_inputs_next_run = True
            st.rerun()

        if not all_valid:
            st.caption("Kaydetmek için tüm ürünlerin fiyatı geçerli olmalı.")

    st.markdown('</div>', unsafe_allow_html=True)


# =========================================================
# 10. EKRANLAR
# =========================================================

def get_current_location_center():
    lat = parse_price(str(st.session_state.get("location_lat", "")))
    lon = parse_price(str(st.session_state.get("location_lon", "")))

    if lat is None or lon is None:
        # İstanbul varsayılan test merkezi
        return 41.0082, 28.9784, 12

    return lat, lon, 16


def apply_detected_location(location):
    """
    streamlit-geolocation sonucu:
    {'latitude': ..., 'longitude': ..., 'accuracy': ...}
    veya ilk açılışta "No Location Info" benzeri string olabilir.
    """
    if not isinstance(location, dict):
        return False

    lat = location.get("latitude")
    lon = location.get("longitude")

    if lat is None:
        lat = location.get("lat")

    if lon is None:
        lon = location.get("lng") or location.get("lon")

    try:
        lat = float(lat)
        lon = float(lon)
    except Exception:
        return False

    st.session_state.location_lat = str(round(lat, 7))
    st.session_state.location_lon = str(round(lon, 7))
    st.session_state.location_accuracy = clean_cell(location.get("accuracy", ""))
    st.session_state.location_source = "GPS"
    return True



def render_location_screen():
    st.subheader("📍 Konum Doğrulama")

    st.caption(
        "Telefonda ilk kullanımda tarayıcı konum izni ister. İzin çıkmazsa adres çubuğundaki kilit simgesinden konum iznini aç."
    )

    if HAS_GEOLOCATION:
        st.markdown("#### 1. GPS ile konum al")
        location = streamlit_geolocation()

        if apply_detected_location(location):
            st.success(
                f"GPS konumu alındı: {st.session_state.location_lat}, {st.session_state.location_lon}"
            )
        else:
            st.info("Konum izni verdikten sonra birkaç saniye bekle. Gerekirse sayfayı yenile veya butona tekrar bas.")
    else:
        st.warning("GPS konum paketi kurulu değil: streamlit-geolocation")

    lat, lon, zoom = get_current_location_center()

    st.markdown("#### 2. Haritada kontrol et")

    if HAS_MAP:
        m = folium.Map(location=[lat, lon], zoom_start=zoom)
        folium.Marker(
            [lat, lon],
            tooltip="Seçili konum",
            popup="Fiş konumu"
        ).add_to(m)
        folium.Circle(
            radius=30,
            location=[lat, lon],
            color="#2563eb",
            fill=True,
            fill_opacity=0.15,
        ).add_to(m)

        map_data = st_folium(m, height=280, width=700)

        # Haritaya tıklanırsa manuel düzeltme olarak kabul et.
        if isinstance(map_data, dict) and map_data.get("last_clicked"):
            clicked = map_data.get("last_clicked", {})
            try:
                st.session_state.location_lat = str(round(float(clicked.get("lat")), 7))
                st.session_state.location_lon = str(round(float(clicked.get("lng")), 7))
                st.session_state.location_source = "Harita"
                st.info("Haritadan seçilen konum alındı. Konumu onaylayabilirsin.")
            except Exception:
                pass
    else:
        st.info("Harita paketi kurulu değil. Konum alanı test modunda çalışıyor.")

    st.markdown("#### 3. Konumu onayla")

    c1, c2 = st.columns(2)

    c1.metric("Enlem", clean_cell(st.session_state.get("location_lat", "")) or "Bekleniyor")
    c2.metric("Boylam", clean_cell(st.session_state.get("location_lon", "")) or "Bekleniyor")

    accuracy = clean_cell(st.session_state.get("location_accuracy", ""))

    if accuracy:
        st.caption(f"GPS doğruluk payı: yaklaşık {accuracy} metre")

    with st.expander("Manuel koordinat gir / düzelt"):
        manual_lat = st.text_input(
            "Enlem",
            value=clean_cell(st.session_state.get("location_lat", "")),
            key="manual_location_lat",
            placeholder="41.0082"
        )
        manual_lon = st.text_input(
            "Boylam",
            value=clean_cell(st.session_state.get("location_lon", "")),
            key="manual_location_lon",
            placeholder="28.9784"
        )

        if st.button("Manuel koordinatı kullan", use_container_width=True):
            try:
                lat_value = float(str(manual_lat).replace(",", "."))
                lon_value = float(str(manual_lon).replace(",", "."))
                st.session_state.location_lat = str(round(lat_value, 7))
                st.session_state.location_lon = str(round(lon_value, 7))
                st.session_state.location_source = "Manuel"
                st.success("Manuel konum kaydedildi. Şimdi konumu onaylayabilirsin.")
                st.rerun()
            except Exception:
                st.error("Enlem/boylam değeri geçersiz.")

    button_label = "Konumu Güncelle" if st.session_state.get("needs_location_update", False) else "Konumu Onayla ve Başla"

    has_coords = bool(clean_cell(st.session_state.get("location_lat", ""))) and bool(clean_cell(st.session_state.get("location_lon", "")))

    if st.button(button_label, use_container_width=True, type="primary", disabled=not has_coords):
        st.session_state.location_confirmed = True
        st.session_state.needs_location_update = False

        if st.session_state.get("research_active", False):
            st.session_state.step = "product_tree"
        else:
            st.session_state.step = "research_start"

        st.rerun()

    if not has_coords:
        st.caption("Konumu onaylamak için GPS izni ver, haritaya tıkla veya manuel koordinat gir.")



def render_research_start_screen():
    st.subheader("Fiyat Araştırması")

    if st.session_state.get("research_active", False):
        st.success(f"Açık araştırma var: {st.session_state.active_research_mode}")

        c1, c2 = st.columns(2)

        if c1.button("▶️ Araştırmaya Devam Et", use_container_width=True, type="primary"):
            st.session_state.step = "product_tree"
            st.rerun()

        if c2.button("🏁 Fiyat Araştırmasını Bitir", use_container_width=True):
            finish_research_session()
            st.rerun()

        return

    st.caption("Fiyat karşılaştırması sadece Başlat ile Bitir arasındaki fişleri değerlendirecek.")

    mode = st.radio(
        "Araştırma modu",
        ["Bugün alacağım", "Geniş fiyat araştırması"],
        key="research_start_mode",
        horizontal=True,
    )

    if st.button("🔍 Fiyat Araştırması Başlat", use_container_width=True, type="primary"):
        start_research_session(mode)
        st.rerun()

    if st.button("📝 Alışveriş Listesi Oluştur", use_container_width=True):
        create_user_shopping_list()
        st.session_state.step = "user_list_builder"
        st.rerun()

    st.markdown("---")

    c_old1, c_old2 = st.columns(2)

    if c_old1.button("📊 Fiyat Araştırmaları", use_container_width=True):
        st.session_state.step = "research_history"
        st.rerun()

    if c_old2.button("🧾 Alışveriş Listeleri", use_container_width=True):
        st.session_state.step = "shopping_history"
        st.rerun()





def sort_user_list_tree_options(options, level_col):
    options = [clean_cell(x) for x in options if clean_cell(x)]

    l1 = clean_cell(st.session_state.get("user_list_level_1", ""))
    l2 = clean_cell(st.session_state.get("user_list_level_2", ""))

    if level_col == "ui_seviye_1":
        order = TREE_OPTION_ORDER["ui_seviye_1"]
    elif level_col == "ui_seviye_2" and l1 == "Gıda":
        order = TREE_OPTION_ORDER["gida_ui_seviye_2"]
    elif level_col == "ui_seviye_3" and l1 == "Gıda" and l2 == "Meyve Sebze":
        order = TREE_OPTION_ORDER["meyve_sebze_ui_seviye_3"]
    elif level_col == "ui_seviye_3" and l1 == "Gıda" and l2 == "Kuru Gıda":
        order = TREE_OPTION_ORDER["kuru_gida_ui_seviye_3"]
    elif level_col == "ui_seviye_2" and l1 == "Elektronik":
        order = TREE_OPTION_ORDER["elektronik_ui_seviye_2"]
    elif level_col == "ui_seviye_3" and l1 == "Elektronik" and l2 == "Bilgisayar & Tablet":
        order = TREE_OPTION_ORDER["bilgisayar_ui_seviye_3"]
    else:
        order = []

    order_map = {name: i for i, name in enumerate(order)}

    return sorted(
        options,
        key=lambda x: (order_map.get(x, 999), normalize_for_search(x))
    )


def get_user_list_filtered_products():
    df = products_df.copy()

    for i, col in enumerate(LEVEL_COLS, start=1):
        selected = clean_cell(st.session_state.get(f"user_list_level_{i}", ""))

        if selected:
            df = df[df[col] == selected]

    return df


def get_user_list_next_level_options():
    df = get_user_list_filtered_products()

    for i, col in enumerate(LEVEL_COLS, start=1):
        selected = clean_cell(st.session_state.get(f"user_list_level_{i}", ""))

        if not selected:
            options = [
                clean_cell(x)
                for x in df[col].dropna().unique()
                if clean_cell(x)
            ]
            options = sort_user_list_tree_options(options, col)
            return i, col, options

    return None, None, []


def reset_user_list_tree(from_level=1):
    for i in range(from_level, 6):
        st.session_state[f"user_list_level_{i}"] = ""

    st.session_state.user_list_product_limit = 12


def get_deepest_user_list_level():
    deepest = 0

    for i in range(1, 6):
        if clean_cell(st.session_state.get(f"user_list_level_{i}", "")):
            deepest = i

    return deepest


def go_up_user_list_tree():
    deepest = get_deepest_user_list_level()

    if deepest <= 1:
        reset_user_list_tree(1)
    else:
        reset_user_list_tree(deepest)


def render_user_list_breadcrumb():
    selected_parts = []

    for i in range(1, 6):
        value = clean_cell(st.session_state.get(f"user_list_level_{i}", ""))

        if value:
            selected_parts.append(value)

    if selected_parts:
        st.caption(" > ".join(selected_parts))


def user_list_product_order_score(row):
    level_1 = clean_cell(st.session_state.get("user_list_level_1", ""))
    level_2 = clean_cell(st.session_state.get("user_list_level_2", ""))
    level_3 = clean_cell(st.session_state.get("user_list_level_3", ""))

    if level_1 != "Gıda" or level_2 != "Meyve Sebze":
        return 9999

    name = normalize_for_search(row.get("urun_adi", ""))

    if level_3 == "Sebzeler":
        order = PRODUCT_ORDER["sebzeler"]
    elif level_3 == "Meyveler":
        order = PRODUCT_ORDER["meyveler"]
    else:
        return 9999

    for i, key in enumerate(order):
        key_norm = normalize_for_search(key)

        if name == key_norm:
            return i * 100

        if name.startswith(key_norm + " ") or key_norm in name:
            return i * 100 + 10

    return 9999


def render_add_products_to_user_list_grid(df, list_id, key_prefix="user_list_grid"):
    if df.empty:
        st.warning("Bu seçimde ürün yok.")
        return

    df = df.copy()
    df["_display_order"] = df.apply(user_list_product_order_score, axis=1)
    df["_name_order"] = df["urun_adi"].apply(normalize_for_search)
    df = df.sort_values(["_display_order", "_name_order"])

    limit = int(st.session_state.user_list_product_limit)
    visible = df.head(limit)

    st.caption(f"Gösterilen: {len(visible)} / {len(df)}")

    rows = list(visible.iterrows())
    cols_per_row = 4

    for start_idx in range(0, len(rows), cols_per_row):
        chunk = rows[start_idx:start_idx + cols_per_row]
        cols = st.columns(cols_per_row)

        for col_idx, (_, row) in enumerate(chunk):
            with cols[col_idx]:
                product_id = clean_cell(row.get("product_id", ""))
                title = format_product_title(row)
                emoji = get_product_icon_emoji(product_id, title) if "get_product_icon_emoji" in globals() else ""
                label = f"{emoji}\\n{title}\\nListeye ekle"

                if st.button(
                    label,
                    key=safe_key(key_prefix, list_id, product_id, start_idx + col_idx),
                    use_container_width=True
                ):
                    add_product_to_user_list(list_id, row)
                    st.rerun()

    if len(df) > limit:
        if st.button("➕ Daha fazla ürün göster", use_container_width=True, key=safe_key(key_prefix, list_id, "more")):
            st.session_state.user_list_product_limit = min(limit + 16, 120)
            st.rerun()


def render_user_list_tree_selector(list_id):
    render_user_list_breadcrumb()

    if any(clean_cell(st.session_state.get(f"user_list_level_{i}", "")) for i in range(1, 6)):
        n1, n2 = st.columns(2)

        if n1.button("⬅️ Bir üst kategoriye dön", use_container_width=True, key="user_list_tree_up"):
            go_up_user_list_tree()
            st.rerun()

        if n2.button("🏠 Başa dön", use_container_width=True, key="user_list_tree_reset"):
            reset_user_list_tree(1)
            st.rerun()

    level_no, level_col, options = get_user_list_next_level_options()
    filtered_products = get_user_list_filtered_products()

    if level_col and options:
        st.markdown("##### Kategori seç")

        cols_count = 2 if len(options) < 8 else 3
        cols = st.columns(cols_count)

        for i, option in enumerate(options):
            count = len(filtered_products[filtered_products[level_col] == option])
            label = f"{option} ({count})"

            if cols[i % cols_count].button(
                label,
                key=safe_key("user_list_level", level_no, option, i),
                use_container_width=True,
            ):
                st.session_state[f"user_list_level_{level_no}"] = option
                reset_user_list_tree(level_no + 1)
                st.rerun()

    product_count = len(filtered_products)

    show_products = (
        product_count <= 60 or
        all(clean_cell(st.session_state.get(f"user_list_level_{i}", "")) for i in range(1, 6)) or
        (level_col is None)
    )

    if show_products:
        st.markdown("##### Ürünler")
        render_add_products_to_user_list_grid(filtered_products, list_id, key_prefix="user_list_tree_product")
    else:
        st.info(f"{product_count} ürün var. Butonlarla kategoriyi biraz daha daralt.")



def render_user_list_builder_screen():
    st.subheader("📝 Alışveriş Listesi Oluştur")

    list_id = clean_cell(st.session_state.get("current_user_list_id", ""))

    if not list_id:
        list_id = create_user_shopping_list()

    lists = read_user_lists()
    current = lists[lists["list_id"] == list_id].copy()

    if current.empty:
        st.warning("Liste bulunamadı.")
        if st.button("Yeni Liste Oluştur", use_container_width=True):
            create_user_shopping_list()
            st.rerun()
        return

    first = current.iloc[0]

    c_name, c_status = st.columns([3, 1])

    list_name = c_name.text_input(
        "Liste adı",
        value=clean_cell(first.get("ad", "")) or "Yeni Alışveriş Listesi",
        key=safe_key("user_list_name", list_id)
    )

    status_options = ["aktif", "tamamlandı"]
    current_status = clean_cell(first.get("status", "")) or "aktif"
    status_index = status_options.index(current_status) if current_status in status_options else 0

    list_status = c_status.selectbox(
        "Durum",
        status_options,
        index=status_index,
        key=safe_key("user_list_status", list_id)
    )

    if list_name != clean_cell(first.get("ad", "")) or list_status != clean_cell(first.get("status", "")):
        update_user_shopping_list(list_id, name=list_name, status=list_status)

    st.caption(f"{first.get('tarih', '')} {first.get('saat', '')} • Liste ID: {list_id}")

    items = read_user_list_items()
    current_items = items[items["list_id"] == list_id].copy()

    st.markdown("#### Listedeki ürünler")

    if current_items.empty:
        st.info("Listeye henüz ürün eklenmedi.")
    else:
        rows = list(current_items.iterrows())
        cols_per_row = 4

        for start_idx in range(0, len(rows), cols_per_row):
            chunk = rows[start_idx:start_idx + cols_per_row]
            cols = st.columns(cols_per_row)

            for col_idx, (_, item) in enumerate(chunk):
                with cols[col_idx]:
                    product_id = clean_cell(item.get("product_id", ""))
                    emoji = get_product_icon_emoji(product_id, item.get("urun", "")) if "get_product_icon_emoji" in globals() else ""

                    st.markdown(
                        f"""
                        <div style="
                            border:1px solid #cbd5e1;
                            border-radius:14px;
                            padding:8px;
                            min-height:96px;
                            background:#ffffff;
                            margin-bottom:6px;
                        ">
                            <div style="font-size:28px;text-align:center;">{emoji}</div>
                            <div style="font-size:13px;font-weight:900;line-height:1.15;color:#0f172a;">{item.get('urun', '')}</div>
                            <div style="font-size:10px;color:#64748b;">{item.get('birim', '')}</div>
                        </div>
                        """,
                        unsafe_allow_html=True
                    )

                    if st.button(
                        "Sil",
                        key=safe_key("remove_user_list_item", list_id, product_id, start_idx + col_idx),
                        use_container_width=True
                    ):
                        remove_product_from_user_list(list_id, product_id)
                        st.rerun()

    st.markdown("---")
    st.markdown("#### Ürün ekle")
    st.caption("İstersen kategorilerden butonla seç, istersen ürün adıyla ara.")

    tab_buttons, tab_search = st.tabs(["Butonla seç", "Arayarak ekle"])

    with tab_buttons:
        render_user_list_tree_selector(list_id)

    with tab_search:
        query = st.text_input(
            "Ürün ara",
            key="user_list_search_query",
            placeholder="Örn: domates, çupra, Galaxy A07, süt..."
        )

        if clean_cell(query):
            results = search_products(query, limit=24)

            if results.empty:
                st.warning("Ürün bulunamadı.")
            else:
                render_add_products_to_user_list_grid(results, list_id, key_prefix="user_list_search_product")

    st.markdown("---")

    c1, c2, c3 = st.columns(3)

    if c1.button("💰 Bu Listeyle Fiyat Gir", use_container_width=True, type="primary"):
        user_list_to_research(list_id, mode="Bugün alacağım")
        st.rerun()

    if c2.button("📋 Listelerim", use_container_width=True):
        st.session_state.step = "user_lists"
        st.rerun()

    if c3.button("⬅️ Ana Menü", use_container_width=True):
        st.session_state.step = "research_start"
        st.rerun()


def render_user_lists_screen():
    st.subheader("📋 Alışveriş Listelerim")
    st.caption("Burada gıda, elektronik, temizlik veya karışık tüm yapılacak alışveriş listelerini ayrı ayrı tutabilirsin.")

    sync_postponed_items_to_user_list()
    lists = read_user_lists()

    if st.button("📝 Yeni Alışveriş Listesi Oluştur", use_container_width=True, type="primary"):
        create_user_shopping_list()
        st.session_state.step = "user_list_builder"
        st.rerun()

    if lists.empty:
        st.info("Henüz alışveriş listesi yok.")
        return

    lists = lists[lists["status"] != "silindi"].copy()

    if lists.empty:
        st.info("Aktif alışveriş listesi yok.")
        return

    status_filter = st.radio(
        "Liste görünümü",
        ["Yapılacaklar", "Tamamlanan", "Tümü"],
        horizontal=True,
        key="user_list_status_filter",
    )

    if status_filter == "Yapılacaklar":
        lists = lists[lists["status"].isin(["aktif", "yapılacak", "devam ediyor", ""])]
    elif status_filter == "Tamamlanan":
        lists = lists[lists["status"] == "tamamlandı"]

    if lists.empty:
        st.info("Bu görünümde liste yok.")
        return

    lists = lists.sort_values(["tarih", "saat"], ascending=[False, False])
    items = read_user_list_items()

    st.markdown("---")

    for i, (_, row) in enumerate(lists.iterrows()):
        list_id = clean_cell(row.get("list_id", ""))
        count = 0

        if not items.empty:
            count = len(items[items["list_id"] == list_id])

        status = clean_cell(row.get("status", "")) or "aktif"
        list_name = clean_cell(row.get("ad", "")) or "Yeni Alışveriş Listesi"

        st.markdown(
            f"**{list_name}**  \n"
            f"{row.get('tarih', '')} {row.get('saat', '')} • {count} ürün • durum: {status}"
        )

        c1, c2, c3, c4 = st.columns(4)

        if c1.button("Düzenle", key=safe_key("edit_user_list", list_id, i), use_container_width=True):
            st.session_state.current_user_list_id = list_id
            st.session_state.step = "user_list_builder"
            st.rerun()

        if c2.button("Fiyat Gir", key=safe_key("price_user_list", list_id, i), use_container_width=True):
            user_list_to_research(list_id, mode="Bugün alacağım")
            st.rerun()

        if status != "tamamlandı":
            if c3.button("Tamamlandı", key=safe_key("complete_user_list", list_id, i), use_container_width=True):
                update_user_shopping_list(list_id, status="tamamlandı")
                st.rerun()
        else:
            if c3.button("Yapılacak", key=safe_key("reactivate_user_list", list_id, i), use_container_width=True):
                update_user_shopping_list(list_id, status="aktif")
                st.rerun()

        if c4.button("Sil", key=safe_key("delete_user_list", list_id, i), use_container_width=True):
            delete_user_shopping_list(list_id)
            st.success("Alışveriş listesi silindi.")
            st.rerun()

        st.divider()




def render_source_type_screen():
    st.subheader("Fiş kaynağı seç")
    st.caption("Bu seçim ürün ağacını açmak için değil, fişi kaydederken fiyatın nereden alındığını belirtmek içindir.")

    if st.button("⬅️ Ürünlere Dön", use_container_width=True):
        st.session_state.step = "product_tree"
        st.rerun()

    if sources_df.empty:
        st.warning("source_master.csv içinde kaynak yok. Elle kaynak girebilirsin.")
    else:
        source_types = [
            clean_cell(x)
            for x in sources_df["source_type"].dropna().unique()
            if clean_cell(x)
        ]

        source_type_order = {
            "Gıda Marketi": 1,
            "Pazar": 2,
            "Esnaf": 3,
            "Elektronik Marketi": 4,
            "Elektronik Market": 4,
            "Online Mağaza": 5,
            "Marka Mağazası": 6,
        }

        source_types = sorted(
            source_types,
            key=lambda x: (source_type_order.get(x, 99), normalize_for_search(x))
        )

        st.caption("Kaynak türleri source_master.csv dosyasından okunuyor.")

        cols = st.columns(2)

        for i, source_type in enumerate(source_types):
            count = len(sources_df[sources_df["source_type"] == source_type])

            if cols[i % 2].button(
                f"{source_type} ({count})",
                key=safe_key("source_type", source_type, i),
                use_container_width=True,
            ):
                st.session_state.selected_source_type = source_type
                st.session_state.source_group_filter = "Tümü"
                st.session_state.step = "source_name"
                st.rerun()

    with st.expander("Kaynağı elle yaz"):
        manual_type = st.text_input("Kaynak türü", placeholder="Örn: Yerel mağaza, bayi, pazar...")
        manual_name = st.text_input("Kaynak adı", placeholder="Örn: Kadıköy Elektronikçi...")

        if st.button("Elle Kaynağı Kullan", use_container_width=True):
            if clean_cell(manual_name):
                select_manual_source(manual_type, manual_name)
                st.rerun()
            else:
                st.error("Kaynak adı boş olamaz.")



def get_receipt_context_for_sources():
    """
    Fişe eklenen ürünlerden kaynak seçiminde kullanılacak bağlamı çıkarır.
    Amaç: Kaynak seçerken tüm marka mağazalarını göstermek yerine,
    fişteki ürünlerin sektör/kategori/markasına uygun kaynakları öne getirmek.
    """
    sectors = set()
    categories = set()
    alt_categories = set()
    product_types = set()
    brands = set()

    for item in st.session_state.receipt_items:
        for key, target_set in [
            ("sektor", sectors),
            ("ana_kategori", categories),
            ("alt_kategori", alt_categories),
            ("urun_turu", product_types),
            ("marka", brands),
        ]:
            value = clean_cell(item.get(key, ""))
            if value:
                target_set.add(value)

    return {
        "sectors": sectors,
        "categories": categories,
        "alt_categories": alt_categories,
        "product_types": product_types,
        "brands": brands,
    }


def split_scope(value):
    return [
        clean_cell(x)
        for x in str(value).split("|")
        if clean_cell(x)
    ]


def source_matches_receipt(row, context):
    if not st.session_state.receipt_items:
        return True

    source_type = clean_cell(row.get("source_type", ""))
    related_brand = clean_cell(row.get("related_brand", ""))
    sector_scope = clean_cell(row.get("sector_scope", ""))
    category_scope_values = split_scope(row.get("category_scope", ""))

    sectors = context["sectors"]
    categories = context["categories"]
    alt_categories = context["alt_categories"]
    product_types = context["product_types"]
    brands = context["brands"]

    if source_type == "Marka Mağazası":
        return related_brand in brands if related_brand else False

    if source_type in ["Elektronik Marketi", "Elektronik Market"]:
        return "Elektronik" in sectors

    if source_type == "Gıda Marketi":
        # Gıda marketleri temizlik ürünleri de sattığı için
        # Temizlik araştırmalarında Kim/Bim/Şok/A-101/Migros gibi kaynaklar da gelmeli.
        return ("Gıda" in sectors) or ("Temizlik" in sectors)

    if source_type in ["Pazar", "Esnaf"]:
        return "Gıda" in sectors

    if source_type == "Online Mağaza":
        return True

    if sector_scope:
        if sector_scope not in sectors:
            return False
    else:
        return False

    if category_scope_values:
        product_scope_values = categories | alt_categories | product_types
        return bool(set(category_scope_values) & product_scope_values)

    return True


def source_relevance_score(row, context):
    score = 0

    if not st.session_state.receipt_items:
        return score

    source_type = clean_cell(row.get("source_type", ""))
    related_brand = clean_cell(row.get("related_brand", ""))
    sector_scope = clean_cell(row.get("sector_scope", ""))
    category_scope_values = split_scope(row.get("category_scope", ""))

    if related_brand and related_brand in context["brands"]:
        score += 100

    if source_type == "Marka Mağazası" and related_brand in context["brands"]:
        score += 50

    if source_type == "Gıda Marketi" and "Temizlik" in context["sectors"]:
        score += 45

    if source_type == "Online Mağaza":
        score += 20

    if sector_scope and sector_scope in context["sectors"]:
        score += 30

    product_scope_values = context["categories"] | context["alt_categories"] | context["product_types"]

    if category_scope_values:
        score += 15 * len(set(category_scope_values) & product_scope_values)

    product_count = pd.to_numeric(row.get("product_count", "0"), errors="coerce")
    if pd.isna(product_count):
        product_count = 0

    score += min(float(product_count), 1000) / 1000

    return score



def get_smart_source_candidates():
    """
    Fişteki ürünlere göre tüm kaynak türleri arasından uygun kaynakları getirir.
    Örnek:
    - Apple ürün varsa Apple Marka Mağazası
    - Elektronik ürün varsa Elektronik Marketi
    - Gıda ürün varsa Gıda Marketi
    - Online mağazalar genel alternatif olarak görünür
    """
    context = get_receipt_context_for_sources()

    if sources_df.empty:
        return pd.DataFrame(columns=sources_df.columns)

    candidates = sources_df.copy()

    if st.session_state.receipt_items:
        candidates = candidates[
            candidates.apply(lambda row: source_matches_receipt(row, context), axis=1)
        ].copy()

    if not candidates.empty:
        candidates["_score"] = candidates.apply(lambda row: source_relevance_score(row, context), axis=1)
        candidates["_pc"] = pd.to_numeric(candidates.get("product_count", "0"), errors="coerce").fillna(0)

        type_order = {
            "Marka Mağazası": 1,
            "Elektronik Marketi": 2,
            "Elektronik Market": 2,
            "Gıda Marketi": 2,
            "Online Mağaza": 3,
            "Pazar": 4,
            "Esnaf": 5,
        }

        candidates["_type_order"] = candidates["source_type"].map(type_order).fillna(99)
        candidates = candidates.sort_values(
            ["_score", "_type_order", "_pc", "source_name"],
            ascending=[False, True, False, True]
        )
        candidates = candidates.drop(columns=["_score", "_pc", "_type_order"])

    return candidates


def get_best_source_suggestion():
    candidates = get_smart_source_candidates()

    if candidates.empty:
        return None

    return candidates.iloc[0]


def confirm_source_row(row):
    st.session_state.source_id = clean_cell(row.get("source_id", ""))
    st.session_state.source_type = clean_cell(row.get("source_type", ""))
    st.session_state.source_name = clean_cell(row.get("source_name", ""))
    st.session_state.source_auto_selected = False
    st.session_state.step = "product_tree"


def render_smart_source_screen():
    st.subheader("Fiş kaynağı")

    if st.button("⬅️ Ürünlere Dön", use_container_width=True):
        st.session_state.step = "product_tree"
        st.rerun()

    candidates = get_smart_source_candidates()

    if candidates.empty:
        st.warning("Fişteki ürünlere göre kaynak önerisi bulunamadı. Kaynağı elle yazabilirsin.")
    else:
        if st.session_state.receipt_items:
            st.caption("Fişteki ürünlerin marka/kategorisine göre önerilen kaynaklar.")
        else:
            st.caption("Fişte ürün yoksa genel kaynak listesi gösterilir.")

        query = st.text_input("Kaynak ara", placeholder="Örn: Apple, MediaMarkt, Trendyol...")

        if clean_cell(query):
            q = normalize_for_search(query)
            candidates = candidates[
                candidates["source_name"].apply(lambda x: q in normalize_for_search(x))
                | candidates["source_type"].apply(lambda x: q in normalize_for_search(x))
            ]

        st.caption(f"{len(candidates)} kaynak")

        for i, (_, row) in enumerate(candidates.iterrows()):
            c1, c2 = st.columns([3, 1])

            c1.markdown(f"**{row['source_name']}**")
            c1.caption(compact_join([
                row.get("source_type", ""),
                row.get("sector_scope", ""),
                row.get("category_scope", ""),
                f"{row.get('product_count', '')} ürün" if clean_cell(row.get("product_count", "")) else "",
            ], sep=" • "))

            if c2.button("Seç", key=safe_key("smart_source_select", row["source_id"], i), use_container_width=True):
                confirm_source_row(row)
                st.rerun()

            st.divider()

    with st.expander("Kaynağı elle yaz"):
        manual_type = st.text_input(
            "Kaynak türü",
            key="manual_source_type_smart",
            placeholder="Örn: Yerel mağaza, bayi, pazar..."
        )
        manual_name = st.text_input(
            "Kaynak adı",
            key="manual_source_name_smart",
            placeholder="Örn: Kadıköy Elektronikçi..."
        )

        if st.button("Elle Kaynağı Kullan", use_container_width=True, key="manual_source_use_smart"):
            if clean_cell(manual_name):
                select_manual_source(manual_type, manual_name)
                st.rerun()
            else:
                st.error("Kaynak adı boş olamaz.")

    # Eski kaynak türü menüsü bilinçli olarak gizlendi.
    # Kaynak değiştirme artık fişteki ürünlere göre daraltılmış liste üzerinden yapılır.


def render_source_name_screen():
    selected_type = clean_cell(st.session_state.get("selected_source_type", ""))

    st.subheader(selected_type or "Kaynak")

    filtered = sources_df[sources_df["source_type"] == selected_type].copy()

    context = get_receipt_context_for_sources()

    if filtered.empty:
        st.warning("Bu kaynak türü altında kayıt yok.")
    else:
        if st.session_state.receipt_items:
            before_count = len(filtered)
            filtered = filtered[
                filtered.apply(lambda row: source_matches_receipt(row, context), axis=1)
            ].copy()

            if not filtered.empty:
                st.caption(
                    f"Fişteki ürünlere göre uygun kaynaklar gösteriliyor. "
                    f"{len(filtered)} / {before_count}"
                )
            else:
                st.warning("Fişteki ürünlere uygun kaynak bulunamadı. İstersen kaynağı elle yazabilirsin.")
                filtered = sources_df[sources_df["source_type"] == selected_type].copy()
                st.caption("Uygun kaynak bulunamadığı için bu türdeki tüm kaynaklar geçici olarak gösteriliyor.")
        else:
            st.caption("Fişte ürün yoksa kaynaklar genel liste olarak gösterilir.")

        query = st.text_input("Kaynak ara", placeholder="Marka / kaynak adı yaz...")

        if clean_cell(query):
            q = normalize_for_search(query)
            filtered = filtered[
                filtered["source_name"].apply(lambda x: q in normalize_for_search(x))
            ]

        if not filtered.empty:
            filtered["_score"] = filtered.apply(lambda row: source_relevance_score(row, context), axis=1)
            filtered["_pc"] = pd.to_numeric(filtered.get("product_count", "0"), errors="coerce").fillna(0)
            filtered = filtered.sort_values(["_score", "_pc", "source_name"], ascending=[False, False, True])
            filtered = filtered.drop(columns=["_score", "_pc"])

        st.caption(f"{len(filtered)} kaynak")

        for i, (_, row) in enumerate(filtered.iterrows()):
            c1, c2 = st.columns([3, 1])

            c1.markdown(f"**{row['source_name']}**")
            c1.caption(compact_join([
                row.get("source_type", ""),
                row.get("sector_scope", ""),
                row.get("category_scope", ""),
                f"{row.get('product_count', '')} ürün" if clean_cell(row.get("product_count", "")) else "",
            ], sep=" • "))

            if c2.button("Seç", key=safe_key("select_source", row["source_id"], i), use_container_width=True):
                select_source_from_row(row)
                st.rerun()

            st.divider()

    with st.expander("Kaynağı elle yaz"):
        manual_type = st.text_input(
            "Kaynak türü",
            value=selected_type,
            key="manual_source_type_from_name",
            placeholder="Örn: Yerel mağaza, bayi, pazar..."
        )
        manual_name = st.text_input(
            "Kaynak adı",
            key="manual_source_name_from_name",
            placeholder="Örn: Kadıköy Elektronikçi..."
        )

        if st.button("Elle Kaynağı Kullan", use_container_width=True, key="manual_source_use_from_name"):
            if clean_cell(manual_name):
                select_manual_source(manual_type, manual_name)
                st.rerun()
            else:
                st.error("Kaynak adı boş olamaz.")

    cback1, cback2 = st.columns(2)

    if cback1.button("⬅️ Kaynak Türüne Dön", use_container_width=True):
        st.session_state.step = "source_type"
        st.rerun()

    if cback2.button("Ürünlere Dön", use_container_width=True):
        st.session_state.step = "product_tree"
        st.rerun()



def render_tree_breadcrumb():
    selected_parts = []

    for i in range(1, 6):
        value = clean_cell(st.session_state.get(f"level_{i}", ""))
        if value:
            selected_parts.append(value)

    if selected_parts:
        st.caption(" > ".join(selected_parts))


def render_product_tree_screen():
    # Eski sürümden kalan ?add_pid=... linkleri varsa oturumu bozmadan temizle.
    try:
        if st.query_params.get("add_pid", ""):
            st.query_params.clear()
    except Exception:
        pass

    if not st.session_state.get("research_active", False):
        st.warning("Ürün eklemek için önce Fiyat Araştırması Başlat.")
        st.session_state.step = "research_start"
        st.rerun()

    st.subheader("Ürün seç")
    render_tree_breadcrumb()

    if any(clean_cell(st.session_state.get(f"level_{i}", "")) for i in range(1, 6)):
        n1, n2 = st.columns(2)

        if n1.button("⬅️ Bir üst kategoriye dön", use_container_width=True):
            go_up_one_level()
            st.rerun()

        if n2.button("🏠 Başa dön", use_container_width=True):
            reset_tree(1)
            st.rerun()

    level_no, level_col, options = get_next_level_options()
    filtered_products = get_filtered_products()

    # İlk görünen alan her zaman ürün ağacı / ana kategoriler olsun.
    if level_col and options:
        if level_no == 1:
            st.markdown("#### Ana Kategoriler")
        else:
            st.markdown("#### Seçimle ilerle")

        cols_count = 2 if len(options) < 8 else 3
        cols = st.columns(cols_count)

        for i, option in enumerate(options):
            count = len(filtered_products[filtered_products[level_col] == option])
            label = f"{option} ({count})"

            if cols[i % cols_count].button(
                label,
                key=safe_key(f"level_{level_no}", option, i),
                use_container_width=True,
            ):
                st.session_state[f"level_{level_no}"] = option
                reset_tree(level_no + 1)
                st.rerun()

    # Seçim yeterince daraldıysa veya tüm seviyeler seçildiyse ürünleri göster.
    product_count = len(filtered_products)

    show_products = (
        product_count <= 60 or
        all(clean_cell(st.session_state.get(f"level_{i}", "")) for i in range(1, 6)) or
        (level_col is None)
    )

    if show_products:
        st.markdown("#### Ürünler")
        render_product_list(filtered_products)
    else:
        st.info(f"{product_count} ürün var. Listeyi açmak yerine yukarıdaki seçimlerle daralt.")

    st.markdown("---")

    with st.expander("🔎 Bulamazsan ara", expanded=False):
        render_quick_search()

    st.markdown("---")
    render_receipt_panel()


def handle_add_product_query(df):
    try:
        add_pid = st.query_params.get("add_pid", "")
    except Exception:
        add_pid = ""

    if isinstance(add_pid, list):
        add_pid = add_pid[0] if add_pid else ""

    add_pid = clean_cell(add_pid)

    if not add_pid:
        return

    matched = products_df[products_df["product_id"] == add_pid].copy()

    if matched.empty:
        matched = df[df["product_id"] == add_pid].copy()

    if not matched.empty:
        add_to_receipt(matched.iloc[0])

    try:
        st.query_params.clear()
    except Exception:
        pass

    st.rerun()


def render_product_list(df):
    if df.empty:
        st.warning("Bu seçimde ürün yok.")
        return

    df = df.copy()

    # Ürün ekleme URL/query-param üzerinden değil, aynı oturumdaki Streamlit butonu üzerinden yapılır.
    df["_display_order"] = df.apply(product_order_score, axis=1)
    df["_name_order"] = df["urun_adi"].apply(normalize_for_search)
    df = df.sort_values(["_display_order", "_name_order"])

    limit = int(st.session_state.product_list_limit)
    visible = df.head(limit)

    st.caption(f"Gösterilen: {len(visible)} / {len(df)}")

    rows = list(visible.iterrows())
    products_per_row = 4

    for start_idx in range(0, len(rows), products_per_row):
        chunk = rows[start_idx:start_idx + products_per_row]
        cols = st.columns(products_per_row)

        for col_idx, (_, row) in enumerate(chunk):
            with cols[col_idx]:
                product_id = clean_cell(row["product_id"])
                title = format_product_title(row)
                emoji = get_product_icon_emoji(product_id, title) if "get_product_icon_emoji" in globals() else ""

                # Kartın kendisi buton: kategori/spec yazıları bilinçli olarak kaldırıldı.
                # Ürün adı tek odak; kalabalık kart görünümünü engeller.
                product_label = f"{emoji}\n{title}\n1 Ekle".strip()

                if st.button(
                    product_label,
                    key=safe_key("add_product_tile", product_id, start_idx + col_idx),
                    use_container_width=True
                ):
                    add_to_receipt(row)
                    st.rerun()

    if len(df) > limit:
        if st.button("➕ Daha fazla ürün göster", use_container_width=True):
            st.session_state.product_list_limit = min(limit + 16, 96)
            st.rerun()


def render_quick_search():
    st.markdown("#### Bulamazsan ara")

    # Streamlit kuralı:
    # Bir widget aynı çalıştırmada oluşturulduktan sonra onun session_state key'i değiştirilemez.
    # Bu yüzden temizleme işlemini bir sonraki rerun'ın başında yapıyoruz.
    if st.session_state.get("clear_search_query_next_run", False):
        st.session_state.search_query = ""
        st.session_state.search_limit = 8
        st.session_state.clear_search_query_next_run = False

    query = st.text_input(
        "Ürün ara",
        key="search_query",
        placeholder="Örn: iPhone 128, Bosch buzdolabı, süt, domates...",
    )

    if not clean_cell(query) or len(normalize_for_search(query)) < 3:
        st.caption("Ana yöntem seçimle ilerlemek. Arama sadece yedek.")
        return

    results = search_products(query, limit=40)

    if results.empty:
        st.warning("Aramada sonuç yok.")
        return

    limit = int(st.session_state.search_limit)
    visible = results.head(limit)

    st.caption(f"Arama sonucu: {len(visible)} / {len(results)}")

    for i, (_, row) in enumerate(visible.iterrows()):
        product_id = row["product_id"]
        title = format_product_title(row)
        subtitle = format_product_subtitle(row)

        c1, c2 = st.columns([4, 1])

        c1.markdown(f"**{title}**")
        c1.caption(subtitle)

        if c2.button("Ekle", key=safe_key("search_add", product_id, i), use_container_width=True):
            add_to_receipt(row)
            st.session_state.clear_search_query_next_run = True
            st.rerun()

        st.divider()

    if len(results) > limit:
        if st.button("Aramada daha fazla göster", use_container_width=True):
            st.session_state.search_limit = min(limit + 8, 40)
            st.rerun()

    if st.button("Aramayı temizle", use_container_width=True):
        st.session_state.clear_search_query_next_run = True
        st.rerun()



# =========================================================
# 11. EN UCUZ / DURAK ÖNERİSİ
# =========================================================


def get_research_history():
    sessions = read_research_sessions()

    if sessions.empty:
        return pd.DataFrame(columns=RESEARCH_SESSION_COLUMNS)

    # Fiş kaydı olan araştırmaları öne alır.
    records = read_saved_price_records()

    if not records.empty and "research_id" in records.columns:
        counts = records[records["research_id"] != ""].groupby("research_id").size().reset_index(name="fis_satiri")
        sessions = sessions.merge(counts, on="research_id", how="left")
    else:
        sessions["fis_satiri"] = 0

    sessions["fis_satiri"] = pd.to_numeric(sessions["fis_satiri"], errors="coerce").fillna(0).astype(int)
    sessions = sessions.sort_values(["baslangic_tarih", "baslangic_saat"], ascending=[False, False]).reset_index(drop=True)

    return sessions


def sync_compare_research_index(history):
    if history.empty:
        st.session_state.research_history_index = 0
        return

    current_id = clean_cell(st.session_state.get("compare_research_id", ""))

    if current_id and current_id in history["research_id"].tolist():
        st.session_state.research_history_index = int(history.index[history["research_id"] == current_id][0])
    else:
        st.session_state.research_history_index = 0
        st.session_state.compare_research_id = history.iloc[0]["research_id"]


def render_research_history_nav():
    history = get_research_history()

    if history.empty:
        return ""

    sync_compare_research_index(history)

    idx = int(st.session_state.get("research_history_index", 0))
    idx = max(0, min(idx, len(history) - 1))
    row = history.iloc[idx]
    st.session_state.compare_research_id = row["research_id"]

    c1, c2, c3 = st.columns([1, 3, 1])

    if c1.button("◀ Önceki", use_container_width=True, disabled=(idx >= len(history) - 1)):
        st.session_state.research_history_index = min(idx + 1, len(history) - 1)
        st.session_state.compare_research_id = history.iloc[st.session_state.research_history_index]["research_id"]
        st.session_state.route_excluded_products = []
        st.session_state.route_excluded_sources = []
        st.rerun()

    tarih = clean_cell(row.get("baslangic_tarih", ""))
    saat = clean_cell(row.get("baslangic_saat", ""))
    mode = clean_cell(row.get("mode", ""))
    status = clean_cell(row.get("status", ""))
    fis_satiri = clean_cell(row.get("fis_satiri", ""))

    c2.markdown(f"**{tarih} {saat} fiyat araştırması**")
    c2.caption(f"{mode} • {status} • kayıt satırı: {fis_satiri}")

    if c3.button("Sonraki ▶", use_container_width=True, disabled=(idx <= 0)):
        st.session_state.research_history_index = max(idx - 1, 0)
        st.session_state.compare_research_id = history.iloc[st.session_state.research_history_index]["research_id"]
        st.session_state.route_excluded_products = []
        st.session_state.route_excluded_sources = []
        st.rerun()

    st.caption(f"Araştırma {idx + 1} / {len(history)}")

    render_research_preview_cards(row.get("research_id", ""), limit=8)

    return row["research_id"]


def read_shopping_sessions():
    if not os.path.exists(SHOPPING_SESSIONS_FILE):
        return pd.DataFrame(columns=SHOPPING_SESSION_COLUMNS)

    try:
        df = pd.read_csv(SHOPPING_SESSIONS_FILE, dtype=str, encoding="utf-8-sig")
    except UnicodeDecodeError:
        df = pd.read_csv(SHOPPING_SESSIONS_FILE, dtype=str, encoding="cp1254")
    except Exception:
        return pd.DataFrame(columns=SHOPPING_SESSION_COLUMNS)

    df = ensure_columns(df, SHOPPING_SESSION_COLUMNS)

    for col in SHOPPING_SESSION_COLUMNS:
        df[col] = df[col].apply(clean_cell)

    return df[SHOPPING_SESSION_COLUMNS]


def read_shopping_items():
    if not os.path.exists(SHOPPING_ITEMS_FILE):
        return pd.DataFrame(columns=SHOPPING_ITEM_COLUMNS)

    try:
        df = pd.read_csv(SHOPPING_ITEMS_FILE, dtype=str, encoding="utf-8-sig")
    except UnicodeDecodeError:
        df = pd.read_csv(SHOPPING_ITEMS_FILE, dtype=str, encoding="cp1254")
    except Exception:
        return pd.DataFrame(columns=SHOPPING_ITEM_COLUMNS)

    df = ensure_columns(df, SHOPPING_ITEM_COLUMNS)

    for col in SHOPPING_ITEM_COLUMNS:
        df[col] = df[col].apply(clean_cell)

    return df[SHOPPING_ITEM_COLUMNS]


def write_shopping_sessions(df):
    df = ensure_columns(df, SHOPPING_SESSION_COLUMNS)[SHOPPING_SESSION_COLUMNS]
    df.to_csv(SHOPPING_SESSIONS_FILE, index=False, encoding="utf-8-sig")


def write_shopping_items(df):
    df = ensure_columns(df, SHOPPING_ITEM_COLUMNS)[SHOPPING_ITEM_COLUMNS]
    df.to_csv(SHOPPING_ITEMS_FILE, index=False, encoding="utf-8-sig")



def delete_shopping_plan(shopping_id):
    shopping_id = clean_cell(shopping_id)

    if not shopping_id:
        return

    sessions = read_shopping_sessions()
    items = read_shopping_items()

    if not sessions.empty:
        sessions = sessions[sessions["shopping_id"] != shopping_id].copy()
        write_shopping_sessions(sessions)

    if not items.empty:
        items = items[items["shopping_id"] != shopping_id].copy()
        write_shopping_items(items)

    if st.session_state.get("current_shopping_id", "") == shopping_id:
        st.session_state.current_shopping_id = ""
        st.session_state.shopping_checked = {}




def read_user_lists():
    if not os.path.exists(USER_LISTS_FILE):
        return pd.DataFrame(columns=USER_LIST_COLUMNS)

    try:
        df = pd.read_csv(USER_LISTS_FILE, dtype=str, encoding="utf-8-sig")
    except UnicodeDecodeError:
        df = pd.read_csv(USER_LISTS_FILE, dtype=str, encoding="cp1254")
    except Exception:
        return pd.DataFrame(columns=USER_LIST_COLUMNS)

    df = ensure_columns(df, USER_LIST_COLUMNS)

    for col in USER_LIST_COLUMNS:
        df[col] = df[col].apply(clean_cell)

    return df[USER_LIST_COLUMNS]


def write_user_lists(df):
    df = ensure_columns(df, USER_LIST_COLUMNS)[USER_LIST_COLUMNS]
    df.to_csv(USER_LISTS_FILE, index=False, encoding="utf-8-sig")


def read_user_list_items():
    if not os.path.exists(USER_LIST_ITEMS_FILE):
        return pd.DataFrame(columns=USER_LIST_ITEM_COLUMNS)

    try:
        df = pd.read_csv(USER_LIST_ITEMS_FILE, dtype=str, encoding="utf-8-sig")
    except UnicodeDecodeError:
        df = pd.read_csv(USER_LIST_ITEMS_FILE, dtype=str, encoding="cp1254")
    except Exception:
        return pd.DataFrame(columns=USER_LIST_ITEM_COLUMNS)

    df = ensure_columns(df, USER_LIST_ITEM_COLUMNS)

    for col in USER_LIST_ITEM_COLUMNS:
        df[col] = df[col].apply(clean_cell)

    return df[USER_LIST_ITEM_COLUMNS]


def write_user_list_items(df):
    df = ensure_columns(df, USER_LIST_ITEM_COLUMNS)[USER_LIST_ITEM_COLUMNS]
    df.to_csv(USER_LIST_ITEMS_FILE, index=False, encoding="utf-8-sig")


def create_user_shopping_list(name="Yeni Alışveriş Listesi"):
    tarih, saat = get_today_strings()
    list_id = "LIST_" + datetime.now().strftime("%Y%m%d%H%M%S") + "_" + uuid.uuid4().hex[:5]

    row = {
        "list_id": list_id,
        "status": "aktif",
        "tarih": tarih,
        "saat": saat,
        "ad": clean_cell(name) or "Yeni Alışveriş Listesi",
        "not": "",
    }

    lists = read_user_lists()
    lists = pd.concat([lists, pd.DataFrame([row])], ignore_index=True)
    write_user_lists(lists)

    st.session_state.current_user_list_id = list_id
    return list_id


def get_latest_user_shopping_list_id():
    lists = read_user_lists()

    if lists.empty:
        return ""

    active = lists[lists["status"] != "silindi"].copy()

    if active.empty:
        return ""

    active = active.sort_values(["tarih", "saat"], ascending=[False, False])
    return clean_cell(active.iloc[0]["list_id"])


def add_product_to_user_list(list_id, product_row):
    list_id = clean_cell(list_id)
    product_id = clean_cell(product_row.get("product_id", ""))

    if not list_id or not product_id:
        return False

    items = read_user_list_items()
    existing = items[
        (items["list_id"] == list_id) &
        (items["product_id"] == product_id)
    ]

    if not existing.empty:
        st.toast("Bu ürün listede zaten var.")
        return False

    tarih, saat = get_today_strings()

    row = {
        "list_id": list_id,
        "product_id": product_id,
        "urun": format_product_title(product_row),
        "birim": clean_cell(product_row.get("birim", "")) or "Adet",
        "tarih": tarih,
        "saat": saat,
    }

    items = pd.concat([items, pd.DataFrame([row])], ignore_index=True)
    write_user_list_items(items)
    return True


def remove_product_from_user_list(list_id, product_id):
    list_id = clean_cell(list_id)
    product_id = clean_cell(product_id)

    if not list_id or not product_id:
        return

    items = read_user_list_items()

    if items.empty:
        return

    items = items[
        ~(
            (items["list_id"] == list_id) &
            (items["product_id"] == product_id)
        )
    ].copy()

    write_user_list_items(items)


def delete_user_shopping_list(list_id):
    list_id = clean_cell(list_id)

    if not list_id:
        return

    lists = read_user_lists()
    items = read_user_list_items()

    if not lists.empty:
        lists = lists[lists["list_id"] != list_id].copy()
        write_user_lists(lists)

    if not items.empty:
        items = items[items["list_id"] != list_id].copy()
        write_user_list_items(items)

    if st.session_state.get("current_user_list_id", "") == list_id:
        st.session_state.current_user_list_id = ""



def update_user_shopping_list(list_id, name=None, status=None):
    list_id = clean_cell(list_id)

    if not list_id:
        return

    lists = read_user_lists()

    if lists.empty:
        return

    mask = lists["list_id"] == list_id

    if not mask.any():
        return

    if name is not None:
        lists.loc[mask, "ad"] = clean_cell(name) or "Yeni Alışveriş Listesi"

    if status is not None:
        lists.loc[mask, "status"] = clean_cell(status) or "aktif"

    write_user_lists(lists)


def user_list_to_research(list_id, mode="Bugün alacağım"):
    """
    Manuel alışveriş listesini fiyat araştırmasına taşır.
    Liste; elektronik, gıda, temizlik veya karışık kategorilerden oluşabilir.
    """
    start_research_session(mode)
    import_user_list_to_receipt(list_id)
    st.session_state.step = "product_tree"



def get_or_create_postponed_list():
    """
    'Sonra al' denilen ürünler kaybolmasın diye aktif yapılacak listesine atılır.
    """
    lists = read_user_lists()
    target_name = "Sonra Alınacaklar"

    if not lists.empty:
        active = lists[
            (lists["status"] != "silindi") &
            (lists["ad"] == target_name)
        ].copy()

        if not active.empty:
            active = active.sort_values(["tarih", "saat"], ascending=[False, False])
            return clean_cell(active.iloc[0]["list_id"])

    return create_user_shopping_list(target_name)


def add_postponed_product_to_user_list(product_id):
    product_id = clean_cell(product_id)

    if not product_id or products_df.empty:
        return

    matched = products_df[products_df["product_id"].astype(str) == product_id].copy()

    if matched.empty:
        return

    list_id = get_or_create_postponed_list()
    add_product_to_user_list(list_id, matched.iloc[0])


def add_postponed_item_row_to_user_list(item_row):
    """
    Sonra al ürününü yapılacak listeye aktarır.
    products_master içinde ürün bulunamazsa shopping_items satırından fallback kayıt açar.
    """
    product_id = clean_cell(item_row.get("product_id", ""))

    if not product_id:
        return

    matched = products_df[products_df["product_id"].astype(str) == product_id].copy() if not products_df.empty else pd.DataFrame()

    if not matched.empty:
        add_postponed_product_to_user_list(product_id)
        return

    list_id = get_or_create_postponed_list()
    items = read_user_list_items()

    existing = items[
        (items["list_id"] == list_id) &
        (items["product_id"] == product_id)
    ]

    if not existing.empty:
        return

    tarih, saat = get_today_strings()

    row = {
        "list_id": list_id,
        "product_id": product_id,
        "urun": clean_cell(item_row.get("urun", "")) or "Sonra alınacak ürün",
        "birim": clean_cell(item_row.get("birim", "")) or "Adet",
        "tarih": tarih,
        "saat": saat,
    }

    items = pd.concat([items, pd.DataFrame([row])], ignore_index=True)
    write_user_list_items(items)


def sync_postponed_items_to_user_list():
    """
    Eski sürümde 'sonra' durumuna alınmış ürünler listeye aktarılmamış olabilir.
    Bu fonksiyon her liste/pending ekranında onları Sonra Alınacaklar listesine taşır.
    """
    items = read_shopping_items()

    if items.empty or "durum" not in items.columns:
        return

    postponed = items[items["durum"] == "sonra"].copy()

    if postponed.empty:
        return

    seen_products = set()

    for _, item_row in postponed.iterrows():
        product_id = clean_cell(item_row.get("product_id", ""))

        if not product_id or product_id in seen_products:
            continue

        seen_products.add(product_id)
        add_postponed_item_row_to_user_list(item_row)


def get_active_user_lists_for_pending():
    sync_postponed_items_to_user_list()
    lists = read_user_lists()

    if lists.empty:
        return lists

    lists = lists[lists["status"].isin(["aktif", "yapılacak", "devam ediyor", ""])].copy()
    lists = lists.sort_values(["tarih", "saat"], ascending=[False, False])
    return lists



def get_user_list_products(list_id):
    list_id = clean_cell(list_id)

    if not list_id:
        return pd.DataFrame(columns=products_df.columns)

    items = read_user_list_items()
    items = items[items["list_id"] == list_id].copy()

    if items.empty or products_df.empty:
        return pd.DataFrame(columns=products_df.columns)

    product_ids = items["product_id"].astype(str).tolist()
    result = products_df[products_df["product_id"].astype(str).isin(product_ids)].copy()

    order = {pid: i for i, pid in enumerate(product_ids)}
    result["_list_order"] = result["product_id"].astype(str).map(order).fillna(9999)
    result = result.sort_values("_list_order").drop(columns=["_list_order"], errors="ignore")

    return result


def import_user_list_to_receipt(list_id):
    product_df = get_user_list_products(list_id)

    if product_df.empty:
        st.warning("Bu alışveriş listesinde ürün yok.")
        return

    added_count = 0

    for _, product_row in product_df.iterrows():
        product_id = clean_cell(product_row.get("product_id", ""))
        already = any(item["product_id"] == product_id for item in st.session_state.receipt_items)

        if already:
            continue

        item = build_receipt_item_from_product_row(product_row)
        st.session_state.receipt_items.append(item)
        added_count += 1

    if added_count:
        st.session_state.source_id = ""
        st.session_state.source_type = ""
        st.session_state.source_name = ""
        st.session_state.source_auto_selected = False

    st.success(f"Alışveriş listesinden {added_count} ürün fişe eklendi.")


def build_shopping_rows_from_route(cheapest_df, research_id, shopping_id, status="yapılacak"):
    tarih, saat = get_today_strings()

    header = {
        "shopping_id": shopping_id,
        "research_id": research_id,
        "status": status,
        "tarih": tarih,
        "saat": saat,
        "toplam": round(float(cheapest_df["en_ucuz_fiyat"].sum()), 2),
        "tasarruf": round(float(cheapest_df["tasarruf"].sum()), 2),
        "tamamlanan_urun": 0,
        "toplam_urun": len(cheapest_df),
        "not": "",
    }

    items = []

    for _, row in cheapest_df.iterrows():
        items.append({
            "shopping_id": shopping_id,
            "research_id": research_id,
            "product_id": clean_cell(row.get("product_id", "")),
            "urun": row.get("urun", ""),
            "source_name": row.get("source_name", ""),
            "source_type": row.get("source_type", ""),
            "birim": row.get("birim", ""),
            "fiyat": row.get("en_ucuz_fiyat", ""),
            "tasarruf": row.get("tasarruf", ""),
            "durum": "bekliyor",
            "tarih": tarih,
            "saat": saat,
        })

    return header, items


def get_or_create_shopping_plan(cheapest_df, research_id):
    """
    Alışverişe Başla denince planı ayrı kaydeder.
    Kullanıcı alışveriş yapmasa bile 'yapılacak' olarak kalır.
    Yeni fiyat araştırmasına karışmaz.
    """
    if cheapest_df.empty or not research_id:
        return ""

    sessions = read_shopping_sessions()
    items = read_shopping_items()

    pending = sessions[
        (sessions["research_id"] == research_id) &
        (sessions["status"].isin(["yapılacak", "devam ediyor"]))
    ].copy()

    if not pending.empty:
        shopping_id = pending.sort_values(["tarih", "saat"], ascending=[False, False]).iloc[0]["shopping_id"]
        return shopping_id

    shopping_id = "PLAN_" + datetime.now().strftime("%Y%m%d%H%M%S") + "_" + uuid.uuid4().hex[:5]
    header, item_rows = build_shopping_rows_from_route(cheapest_df, research_id, shopping_id, status="yapılacak")

    sessions = pd.concat([sessions, pd.DataFrame([header])], ignore_index=True)
    items = pd.concat([items, pd.DataFrame(item_rows)], ignore_index=True)

    write_shopping_sessions(sessions)
    write_shopping_items(items)

    return shopping_id


def load_shopping_checked_from_plan(shopping_id):
    items = read_shopping_items()

    if items.empty:
        st.session_state.shopping_checked = {}
        return

    subset = items[items["shopping_id"] == shopping_id]
    checked = {}

    for _, row in subset.iterrows():
        checked[row["product_id"]] = row["durum"] == "alındı"

    st.session_state.shopping_checked = checked


def update_shopping_plan_from_state(shopping_id, complete=False):
    if not shopping_id:
        return

    sessions = read_shopping_sessions()
    items = read_shopping_items()

    if sessions.empty or items.empty:
        return

    mask = items["shopping_id"] == shopping_id
    checked = st.session_state.get("shopping_checked", {})

    for idx, row in items[mask].iterrows():
        product_id = clean_cell(row.get("product_id", ""))
        current_status = clean_cell(row.get("durum", ""))

        # "sonra" durumundaki ürünler yeni araştırmaya / aktif alışverişe karışmasın.
        if current_status == "sonra":
            continue

        items.at[idx, "durum"] = "alındı" if checked.get(product_id, False) else "bekliyor"

    subset = items[mask]
    active_subset = subset[subset["durum"] != "sonra"].copy()
    completed_count = int((active_subset["durum"] == "alındı").sum())
    total_count = len(active_subset)

    session_mask = sessions["shopping_id"] == shopping_id

    if session_mask.any():
        sessions.loc[session_mask, "tamamlanan_urun"] = str(completed_count)
        sessions.loc[session_mask, "toplam_urun"] = str(total_count)
        sessions.loc[session_mask, "status"] = "tamamlandı" if complete else "devam ediyor"

    write_shopping_sessions(sessions)
    write_shopping_items(items)


def get_pending_shopping_plans():
    sessions = read_shopping_sessions()

    if sessions.empty:
        return sessions

    pending = sessions[sessions["status"].isin(["yapılacak", "devam ediyor"])].copy()
    pending = pending.sort_values(["tarih", "saat"], ascending=[False, False])

    return pending


def enrich_route_categories(route_df):
    """
    Rota ürünlerini ürün ağacındaki kategori bilgisiyle zenginleştirir.
    Amaç: Kaynak altında kategori bölümleri ve ürün kutuları göstermek.
    """
    if route_df.empty:
        return route_df

    df = route_df.copy()

    product_cols = [
        "product_id",
        "ui_seviye_1",
        "ui_seviye_2",
        "ui_seviye_3",
        "ui_seviye_4",
        "marka",
        "urun_adi",
    ]

    master = products_df.copy()
    master = ensure_columns(master, product_cols)[product_cols]

    df = df.merge(
        master,
        on="product_id",
        how="left",
        suffixes=("", "_master")
    )

    def route_category(row):
        parts = [
            clean_cell(row.get("ui_seviye_1", "")),
            clean_cell(row.get("ui_seviye_2", "")),
        ]
        parts = [x for x in parts if x]

        if parts:
            return " > ".join(parts)

        path = clean_cell(row.get("path", ""))
        if path:
            split = [x.strip() for x in path.split(">") if x.strip()]
            return " > ".join(split[:2]) if split else "Diğer"

        return "Diğer"

    def route_subcategory(row):
        parts = [
            clean_cell(row.get("ui_seviye_3", "")),
            clean_cell(row.get("ui_seviye_4", "")),
        ]
        parts = [x for x in parts if x]

        if parts:
            return " > ".join(parts)

        return "Genel"

    df["route_category"] = df.apply(route_category, axis=1)
    df["route_subcategory"] = df.apply(route_subcategory, axis=1)

    return df


def get_route_sort_values(row):
    """
    Rota içinde ürünleri sade ve pratik sıraya dizer.
    Kaynak içinde kategori başlığı ayrı satır açmaz; kategori bilgisi ürün kutusunun içinde görünür.
    """
    category = clean_cell(row.get("route_category", ""))
    subcategory = clean_cell(row.get("route_subcategory", ""))
    name = normalize_for_search(row.get("urun", ""))

    category_order = {
        "Gıda": 1,
        "Gıda > Meyve Sebze": 2,
        "Gıda > Kuru Gıda": 3,
        "Gıda > Şarküteri": 4,
        "Gıda > Et Tavuk Balık": 5,
        "Temizlik": 6,
        "Elektronik": 7,
        "Elektronik > Telefon": 8,
        "Elektronik > Bilgisayar & Tablet": 9,
        "Elektronik > Beyaz Eşya & Ev Aletleri": 10,
        "Elektronik > Ev & Yaşam": 11,
    }

    sub_order = {
        "Sebzeler": 1,
        "Meyveler": 2,
        "Kuru Bakliyat": 3,
        "Temel Gıda": 4,
        "Baharat": 5,
        "Kuruyemiş": 6,
        "İçecekler": 7,
        "Paketli Gıda": 8,
    }

    cat_rank = category_order.get(category, 999)
    sub_rank = sub_order.get(subcategory.split(" > ")[0] if subcategory else "", 999)

    return cat_rank, sub_rank, name


def refresh_shopping_session_counts(shopping_id):
    if not shopping_id:
        return

    sessions = read_shopping_sessions()
    items = read_shopping_items()

    if sessions.empty or items.empty:
        return

    mask = items["shopping_id"] == shopping_id
    active_items = items[mask & (items["durum"] != "sonra")].copy()

    completed_count = int((active_items["durum"] == "alındı").sum())
    total_count = len(active_items)

    session_mask = sessions["shopping_id"] == shopping_id

    if session_mask.any():
        sessions.loc[session_mask, "tamamlanan_urun"] = str(completed_count)
        sessions.loc[session_mask, "toplam_urun"] = str(total_count)
        if clean_cell(sessions.loc[session_mask, "status"].iloc[0]) != "tamamlandı":
            sessions.loc[session_mask, "status"] = "devam ediyor"

    write_shopping_sessions(sessions)
    write_shopping_items(items)


def set_shopping_item_status(product_id, status):
    shopping_id = clean_cell(st.session_state.get("current_shopping_id", ""))
    product_id = clean_cell(product_id)
    status = clean_cell(status)

    if not shopping_id or not product_id:
        return

    items = read_shopping_items()

    if items.empty:
        return

    mask = (items["shopping_id"] == shopping_id) & (items["product_id"] == product_id)

    if not mask.any():
        return

    items.loc[mask, "durum"] = status
    write_shopping_items(items)

    if status == "alındı":
        st.session_state.shopping_checked[product_id] = True
    elif status == "bekliyor":
        st.session_state.shopping_checked[product_id] = False
    elif status == "sonra":
        st.session_state.shopping_checked[product_id] = False
        exclude_route_product(product_id)

        for _, item_row in items[mask].iterrows():
            add_postponed_item_row_to_user_list(item_row)

    refresh_shopping_session_counts(shopping_id)


def set_many_shopping_items_status(product_ids, status):
    for product_id in product_ids:
        set_shopping_item_status(product_id, status)


def handle_route_query_actions(route_df, shopping_mode=False):
    # Eski sürümde alışveriş kartları query-param linkleriyle çalışıyordu.
    # Bazı tarayıcılarda yeni sekme/yeni oturum açıp konum ekranına döndürdüğü için devre dışı.
    return




def get_section_label(row):
    sub = clean_cell(row.get("route_subcategory", ""))

    if sub and sub != "Genel":
        return sub.split(" > ")[-1].strip()

    cat = clean_cell(row.get("route_category", ""))

    if cat:
        return cat.split(">")[-1].strip()

    return "Diğer"


def exclude_route_product(product_id):
    product_id = clean_cell(product_id)

    if not product_id:
        return

    excluded = set(st.session_state.get("route_excluded_products", []))
    excluded.add(product_id)
    st.session_state.route_excluded_products = sorted(excluded)


def exclude_route_source(source_name):
    source_name = clean_cell(source_name)

    if not source_name:
        return

    excluded = set(st.session_state.get("route_excluded_sources", []))
    excluded.add(source_name)
    st.session_state.route_excluded_sources = sorted(excluded)


def clear_route_exclusions():
    st.session_state.route_excluded_products = []
    st.session_state.route_excluded_sources = []


def render_product_route_card(row, shopping_mode=False, unique_key=""):
    product_id = clean_cell(row.get("product_id", ""))
    is_done = bool(st.session_state.shopping_checked.get(product_id, False))

    price_text = format_price(str(row.get("en_ucuz_fiyat", "")))
    saving_text = format_price(str(row.get("tasarruf", "")))
    high_text = format_price(str(row.get("en_yuksek_fiyat", "")))
    birim = clean_cell(row.get("birim", "")) or "Adet"

    if shopping_mode:
        # Alışveriş listesinde daha küçük ve operasyonel kutu.
        icon_emoji = get_product_icon_emoji(product_id, str(row.get("urun", ""))) if "get_product_icon_emoji" in globals() else ""
        durum = "✅ ALINDI" if is_done else "🟡 BEKLİYOR"
        label = "\\n".join([
            f"{icon_emoji} {row.get('urun', '')}".strip(),
            f"{price_text} ₺",
            f"Birim: {birim}",
            durum,
        ])

        if st.button(
            label,
            key=safe_key("shopping_toggle_tile", product_id, unique_key),
            use_container_width=True,
            type="primary" if is_done else "secondary",
        ):
            set_shopping_item_status(product_id, "bekliyor" if is_done else "alındı")
            st.rerun()

        if st.button(
            "Sonra al",
            key=safe_key("postpone_shopping_route_item", product_id, unique_key),
            use_container_width=True
        ):
            set_shopping_item_status(product_id, "sonra")
            st.rerun()

        return

    icon_html = get_product_icon_html(product_id, str(row.get("urun", "")), size=60)

    st.markdown(
        f"""
        <div style="
            border:2px solid #e2e8f0;
            background:#ffffff;
            border-radius:14px;
            padding:8px;
            min-height:190px;
            margin-bottom:6px;
        ">
            <div style="font-weight:900; font-size:13px; line-height:1.16; min-height:30px;">{row.get('urun', '')}</div>
            <div style="margin-top:5px;">{icon_html}</div>
            <div style="font-size:18px; color:#0f172a; margin-top:5px;"><b>{price_text} ₺</b></div>
            <div style="font-size:10px; color:#0f172a; font-weight:800;">Birim: {birim}</div>
            <div style="font-size:9px; color:#64748b;">Tasarruf: {saving_text} ₺ • Yüksek: {high_text} ₺</div>
        </div>
        """,
        unsafe_allow_html=True
    )

    if st.button(
        "Rotadan çıkar",
        key=safe_key("remove_route_item", product_id, unique_key),
        use_container_width=True
    ):
        exclude_route_product(product_id)
        st.rerun()


def get_route_sort_values(row):
    category = clean_cell(row.get("route_category", ""))
    section = get_section_label(row)
    name = normalize_for_search(row.get("urun", ""))

    category_order = {
        "Gıda": 1,
        "Gıda > Meyve Sebze": 2,
        "Gıda > Kuru Gıda": 3,
        "Gıda > Şarküteri": 4,
        "Gıda > Et Tavuk Balık": 5,
        "Temizlik": 6,
        "Elektronik": 7,
        "Elektronik > Telefon": 8,
        "Elektronik > Bilgisayar & Tablet": 9,
        "Elektronik > Beyaz Eşya & Ev Aletleri": 10,
        "Elektronik > Ev & Yaşam": 11,
    }

    section_order = {
        "Sebzeler": 1,
        "Meyveler": 2,
        "Meyve Sebze": 3,
        "Kuru Bakliyat": 4,
        "Temel Gıda": 5,
        "Baharat": 6,
        "Kuruyemiş": 7,
        "İçecekler": 8,
        "Paketli Gıda": 9,
    }

    return (
        category_order.get(category, 999),
        section_order.get(section, 999),
        name
    )


def render_route_cards(cheapest_df, shopping_mode=False, research_id=""):
    if cheapest_df.empty:
        return

    route_df = enrich_route_categories(cheapest_df)

    # Bölüm adı önce üretilecek ki bölüm başlığına tıklanınca bütün bölüm alındı yapılabilsin.
    route_df["section_label"] = route_df.apply(get_section_label, axis=1)

    handle_route_query_actions(route_df, shopping_mode=shopping_mode)

    excluded_products = set(st.session_state.get("route_excluded_products", []))
    excluded_sources = set(st.session_state.get("route_excluded_sources", []))

    if excluded_products:
        route_df = route_df[~route_df["product_id"].astype(str).isin(excluded_products)].copy()

    if excluded_sources:
        route_df = route_df[~route_df["source_name"].astype(str).isin(excluded_sources)].copy()

    if route_df.empty:
        st.warning("Rota filtresi sonrası gösterilecek ürün kalmadı.")
        if st.button("Rota filtrelerini temizle", use_container_width=True):
            clear_route_exclusions()
            st.rerun()
        return

    if excluded_products or excluded_sources:
        cinfo, cclear = st.columns([3, 1])
        cinfo.caption(
            f"Sonraya bırakılan/rotadan çıkarılan ürün/kaynak var. "
            f"Ürün: {len(excluded_products)} • Kaynak: {len(excluded_sources)}"
        )
        if cclear.button("Filtreleri Temizle", use_container_width=True):
            clear_route_exclusions()
            st.rerun()

    source_order = (
        route_df
        .groupby("source_name")["en_ucuz_fiyat"]
        .sum()
        .sort_values()
        .index
        .tolist()
    )

    products_per_row = 4

    for source_idx, source_name in enumerate(source_order):
        group = route_df[route_df["source_name"] == source_name].copy()

        source_total = round(float(group["en_ucuz_fiyat"].sum()), 2)
        source_saving = round(float(group["tasarruf"].sum()), 2)
        source_type = compact_join(group["source_type"].dropna().unique(), sep=", ")

        with st.container(border=True):
            source_title = f"{source_name}"
            source_caption = (
                f"{len(group)} ürün • Toplam {format_price(str(source_total))} ₺ • "
                f"Tasarruf {format_price(str(source_saving))} ₺"
            )

            st.markdown(f"### {source_title}")
            st.caption(source_caption)

            if shopping_mode:
                if st.button(
                    "Bu marketteki tüm ürünleri alındı yap",
                    key=safe_key("source_done_button", source_name, source_idx),
                    use_container_width=True
                ):
                    set_many_shopping_items_status(group["product_id"].astype(str).tolist(), "alındı")
                    st.rerun()

            if source_type:
                st.caption(source_type)

            sort_values = group.apply(get_route_sort_values, axis=1, result_type="expand")
            sort_values.columns = ["_cat_rank", "_section_rank", "_name_rank"]
            group = pd.concat([group.reset_index(drop=True), sort_values.reset_index(drop=True)], axis=1)
            group = group.sort_values(["_cat_rank", "_section_rank", "_name_rank"])

            section_order = []
            for _, row in group.iterrows():
                section = clean_cell(row.get("section_label", "")) or "Diğer"
                if section not in section_order:
                    section_order.append(section)

            for section_idx, section_label in enumerate(section_order):
                section_group = group[group["section_label"] == section_label].copy()
                section_total = round(float(section_group["en_ucuz_fiyat"].sum()), 2)

                st.markdown(
                    f"""
                    <div style="
                        background:#e2e8f0;
                        border-radius:12px;
                        padding:7px 10px;
                        margin:10px 0 8px 0;
                        font-weight:900;
                        color:#0f172a;
                        font-size:14px;
                    ">
                        {section_label} <span style="font-weight:600; color:#475569;">• {len(section_group)} ürün • {format_price(str(section_total))} ₺</span>
                    </div>
                    """,
                    unsafe_allow_html=True
                )

                if shopping_mode:
                    if st.button(
                        f"{section_label} bölümünü alındı yap",
                        key=safe_key("section_done_button", source_name, section_label, section_idx),
                        use_container_width=True
                    ):
                        set_many_shopping_items_status(section_group["product_id"].astype(str).tolist(), "alındı")
                        st.rerun()

                rows = list(section_group.iterrows())

                for start_idx in range(0, len(rows), products_per_row):
                    chunk = rows[start_idx:start_idx + products_per_row]
                    cols = st.columns(products_per_row)

                    for col_idx, (_, row) in enumerate(chunk):
                        with cols[col_idx]:
                            unique_key = f"{source_idx}_{section_idx}_{start_idx}_{col_idx}"
                            render_product_route_card(row, shopping_mode=shopping_mode, unique_key=unique_key)


def shopping_items_to_route_df(items_df):
    if items_df.empty:
        return pd.DataFrame()

    rows = []

    for _, row in items_df.iterrows():
        fiyat = parse_price(row.get("fiyat", ""))
        tasarruf = parse_price(row.get("tasarruf", "")) or 0

        rows.append({
            "product_id": row.get("product_id", ""),
            "urun": row.get("urun", ""),
            "birim": row.get("birim", "") or "Adet",
            "path": "",
            "en_ucuz_fiyat": fiyat or 0,
            "en_yuksek_fiyat": (fiyat or 0) + tasarruf,
            "tasarruf": tasarruf,
            "source_name": row.get("source_name", ""),
            "source_type": row.get("source_type", ""),
            "tarih": row.get("tarih", ""),
            "saat": row.get("saat", ""),
        })

    return pd.DataFrame(rows)


def render_shopping_mode_screen():
    st.subheader("🛒 Alışveriş Planı")

    shopping_id = clean_cell(st.session_state.get("current_shopping_id", ""))

    if not shopping_id:
        st.warning("Alışveriş planı seçilmedi.")
        if st.button("📋 Yapılacak Alışverişlere Git", use_container_width=True):
            st.session_state.step = "pending_shopping"
            st.rerun()
        return

    items = read_shopping_items()
    plan_items = items[(items["shopping_id"] == shopping_id) & (items["durum"] != "sonra")].copy()

    if plan_items.empty:
        st.warning("Bu alışveriş planında ürün yok.")
        return

    load_shopping_checked_from_plan(shopping_id)
    route_df = shopping_items_to_route_df(plan_items)

    session_df = read_shopping_sessions()
    plan = session_df[session_df["shopping_id"] == shopping_id]

    if not plan.empty:
        first = plan.iloc[0]
        st.caption(
            f"{first.get('tarih', '')} {first.get('saat', '')} • "
            f"Durum: {first.get('status', '')} • "
            f"Araştırma: {first.get('research_id', '')}"
        )

    render_route_cards(route_df, shopping_mode=True, research_id="")

    total_items = len(plan_items)
    done_items = sum(1 for pid in plan_items["product_id"].astype(str) if st.session_state.shopping_checked.get(pid, False))

    st.info(f"Tamamlanan: {done_items} / {total_items}")

    c1, c2 = st.columns(2)

    if c1.button("💾 Alışverişi Tamamla ve Kaydet", use_container_width=True, type="primary"):
        # Kullanıcı 'tamamla' dediğinde aktif listede kalan ürünleri alınmış kabul ediyoruz.
        # 'Sonra al' ürünleri aktif alışverişten ayrıdır ve Sonra Alınacaklar listesine atılır.
        set_many_shopping_items_status(plan_items["product_id"].astype(str).tolist(), "alındı")
        update_shopping_plan_from_state(shopping_id, complete=True)
        st.session_state.current_shopping_id = ""
        st.session_state.shopping_checked = {}
        st.success("Alışveriş tamamlandı. Ana menüye dönülüyor.")
        st.session_state.step = "research_start"
        st.rerun()

    if c2.button("🏠 Ana Menü / Yeni Fiyat Girişi", use_container_width=True):
        st.session_state.step = "research_start"
        st.rerun()


def render_pending_shopping_screen():
    st.subheader("📋 Yapılacak Alışverişler")

    sync_postponed_items_to_user_list()

    pending = get_pending_shopping_plans()
    active_lists = get_active_user_lists_for_pending()

    if pending.empty and active_lists.empty:
        st.info("Bekleyen alışveriş planı veya yapılacak ürün listesi yok.")
        if st.button("⬅️ Ana Menü", use_container_width=True):
            st.session_state.step = "research_start"
            st.rerun()
        return

    if not active_lists.empty:
        st.markdown("#### Yapılacak ürün listeleri")
        list_items = read_user_list_items()

        for li, (_, list_row) in enumerate(active_lists.iterrows()):
            list_id = clean_cell(list_row.get("list_id", ""))
            count = 0

            if not list_items.empty:
                count = len(list_items[list_items["list_id"] == list_id])

            st.markdown(
                f"**{list_row.get('ad', 'Alışveriş Listesi')}**  \n"
                f"{list_row.get('tarih', '')} {list_row.get('saat', '')} • {count} ürün"
            )

            l1, l2, l3 = st.columns(3)

            if l1.button("Düzenle", key=safe_key("pending_edit_user_list", list_id, li), use_container_width=True):
                st.session_state.current_user_list_id = list_id
                st.session_state.step = "user_list_builder"
                st.rerun()

            if l2.button("Fiyat Gir", key=safe_key("pending_price_user_list", list_id, li), use_container_width=True):
                user_list_to_research(list_id, mode="Bugün alacağım")
                st.rerun()

            if l3.button("Tamamlandı", key=safe_key("pending_complete_user_list", list_id, li), use_container_width=True):
                update_user_shopping_list(list_id, status="tamamlandı")
                st.rerun()

            st.divider()

    if pending.empty:
        return

    st.markdown("#### Rotalı alışveriş planları")

    for i, (_, row) in enumerate(pending.iterrows()):
        st.markdown(
            f"**{row['tarih']} {row['saat']} alışveriş planı**  \n"
            f"Toplam: {format_price(str(row['toplam']))} ₺ • "
            f"Tasarruf: {format_price(str(row['tasarruf']))} ₺ • "
            f"Durum: {row['status']} • "
            f"{row['tamamlanan_urun']}/{row['toplam_urun']} ürün"
        )

        c1, c2, c3, c4 = st.columns(4)

        if c1.button("Devam Et", key=safe_key("continue_plan", row["shopping_id"], i), use_container_width=True):
            st.session_state.current_shopping_id = row["shopping_id"]
            load_shopping_checked_from_plan(row["shopping_id"])
            st.session_state.step = "shopping_mode"
            st.rerun()

        if c2.button("Rota", key=safe_key("show_plan_route", row["shopping_id"], i), use_container_width=True):
            st.session_state.compare_research_id = row["research_id"]
            st.session_state.current_shopping_id = row["shopping_id"]
            st.session_state.step = "compare_prices"
            st.rerun()

        if c3.button("Fiyat Gir", key=safe_key("continue_research_from_pending", row["research_id"], i), use_container_width=True):
            continue_research_session(row["research_id"])
            st.rerun()

        if c4.button("Sil", key=safe_key("delete_pending_plan", row["shopping_id"], i), use_container_width=True):
            delete_shopping_plan(row["shopping_id"])
            st.success("Alışveriş listesi silindi.")
            st.rerun()

        st.divider()

def render_shopping_history_screen():
    st.subheader("🧾 Alışveriş Listeleri")

    sync_postponed_items_to_user_list()

    active_lists = get_active_user_lists_for_pending()

    if not active_lists.empty:
        st.markdown("#### Yapılacak ürün listeleri")
        list_items = read_user_list_items()

        for li, (_, list_row) in enumerate(active_lists.iterrows()):
            list_id = clean_cell(list_row.get("list_id", ""))
            count = 0

            if not list_items.empty:
                count = len(list_items[list_items["list_id"] == list_id])

            st.markdown(
                f"**{list_row.get('ad', 'Alışveriş Listesi')}**  \n"
                f"{list_row.get('tarih', '')} {list_row.get('saat', '')} • {count} ürün • durum: {list_row.get('status', '')}"
            )

            l1, l2, l3 = st.columns(3)

            if l1.button("Düzenle", key=safe_key("history_edit_user_list", list_id, li), use_container_width=True):
                st.session_state.current_user_list_id = list_id
                st.session_state.step = "user_list_builder"
                st.rerun()

            if l2.button("Fiyat Gir", key=safe_key("history_price_user_list", list_id, li), use_container_width=True):
                user_list_to_research(list_id, mode="Bugün alacağım")
                st.rerun()

            if l3.button("Tamamlandı", key=safe_key("history_complete_user_list", list_id, li), use_container_width=True):
                update_user_shopping_list(list_id, status="tamamlandı")
                st.rerun()

            st.divider()

    sessions = read_shopping_sessions()

    if sessions.empty:
        if active_lists.empty:
            st.info("Henüz alışveriş listesi yok.")
            if st.button("⬅️ Ana Menü", use_container_width=True):
                st.session_state.step = "research_start"
                st.rerun()
        return

    st.markdown("#### Rotalı alışveriş kayıtları")
    sessions = sessions.sort_values(["tarih", "saat"], ascending=[False, False])

    status_filter = st.radio(
        "Liste durumu",
        ["Tümü", "Yapılacak / devam ediyor", "Tamamlanan"],
        horizontal=True,
        key="shopping_history_filter",
    )

    filtered = sessions.copy()

    if status_filter == "Yapılacak / devam ediyor":
        filtered = filtered[filtered["status"].isin(["yapılacak", "devam ediyor"])]
    elif status_filter == "Tamamlanan":
        filtered = filtered[filtered["status"] == "tamamlandı"]

    if filtered.empty:
        st.info("Bu filtrede alışveriş listesi yok.")
        return

    for i, (_, row) in enumerate(filtered.iterrows()):
        st.markdown(
            f"**{row['tarih']} {row['saat']} alışveriş listesi**  \\n"
            f"Toplam: {format_price(str(row['toplam']))} ₺ • "
            f"Tasarruf: {format_price(str(row['tasarruf']))} ₺ • "
            f"Durum: {row['status']} • "
            f"{row['tamamlanan_urun']}/{row['toplam_urun']} ürün"
        )

        c1, c2, c3, c4 = st.columns(4)

        if c1.button("Listeyi Aç", key=safe_key("open_shopping_history", row["shopping_id"], i), use_container_width=True):
            st.session_state.current_shopping_id = row["shopping_id"]
            load_shopping_checked_from_plan(row["shopping_id"])
            st.session_state.step = "shopping_mode"
            st.rerun()

        if c2.button("Rotası", key=safe_key("route_shopping_history", row["shopping_id"], i), use_container_width=True):
            st.session_state.compare_research_id = row["research_id"]
            st.session_state.current_shopping_id = row["shopping_id"]
            st.session_state.step = "compare_prices"
            st.rerun()

        if c3.button("Fiyat Gir", key=safe_key("continue_research_from_shopping", row["research_id"], i), use_container_width=True):
            continue_research_session(row["research_id"])
            st.rerun()

        if c4.button("Sil", key=safe_key("delete_shopping_history", row["shopping_id"], i), use_container_width=True):
            delete_shopping_plan(row["shopping_id"])
            st.success("Alışveriş listesi silindi.")
            st.rerun()

        st.divider()












def get_research_preview_records(research_id, limit=8):
    research_id = clean_cell(research_id)

    if not research_id:
        return pd.DataFrame()

    records = read_saved_price_records()

    if records.empty or "research_id" not in records.columns:
        return pd.DataFrame()

    subset = records[records["research_id"] == research_id].copy()

    if subset.empty:
        return pd.DataFrame()

    subset["_sort_time"] = subset["tarih"].astype(str) + " " + subset["saat"].astype(str)
    subset = subset.sort_values("_sort_time", ascending=False)

    return subset.head(limit)


def render_research_preview_cards(research_id, limit=8):
    preview = get_research_preview_records(research_id, limit=limit)

    if preview.empty:
        st.info("Bu araştırmada henüz kayıtlı fiş/fiyat yok. Devam Et ile ürün ve fiyat ekleyebilirsin.")
        return

    st.caption("Bu araştırmada kayıtlı son ürünler:")

    rows = list(preview.iterrows())
    cols_per_row = 4

    for start_idx in range(0, len(rows), cols_per_row):
        chunk = rows[start_idx:start_idx + cols_per_row]
        cols = st.columns(cols_per_row)

        for col_idx, (_, item) in enumerate(chunk):
            with cols[col_idx]:
                product_id = clean_cell(item.get("product_id", ""))
                urun = clean_cell(item.get("urun_adi", "")) or clean_cell(item.get("model", "")) or "Ürün"
                fiyat = format_price(str(item.get("fiyat", "")))
                source = clean_cell(item.get("source_name", ""))
                birim = clean_cell(item.get("birim", ""))

                emoji = get_product_icon_emoji(product_id, urun) if "get_product_icon_emoji" in globals() else ""

                st.markdown(
                    f"""
                    <div style="
                        border:1px solid #cbd5e1;
                        border-radius:12px;
                        padding:7px;
                        min-height:92px;
                        background:#ffffff;
                        margin-bottom:6px;
                    ">
                        <div style="font-size:22px;text-align:center;">{emoji}</div>
                        <div style="font-size:12px;font-weight:900;line-height:1.12;color:#0f172a;">{urun}</div>
                        <div style="font-size:13px;font-weight:900;color:#0f172a;margin-top:4px;">{fiyat} ₺</div>
                        <div style="font-size:10px;color:#64748b;">{birim} • {source}</div>
                    </div>
                    """,
                    unsafe_allow_html=True
                )

def render_research_history_screen():
    st.subheader("📊 Fiyat Araştırmaları")

    history = get_research_history()

    if history.empty:
        st.info("Henüz fiyat araştırması yok.")
        if st.button("⬅️ Ana Menü", use_container_width=True):
            st.session_state.step = "research_start"
            st.rerun()
        return

    active_id = clean_cell(st.session_state.get("active_research_id", ""))

    st.caption("Devam Et dersen yeni fiyatlar aynı araştırmanın içine eklenir. Rota hesabı o araştırmadaki tüm fişleri birlikte kıyaslar.")

    for i, (_, row) in enumerate(history.iterrows()):
        research_id = clean_cell(row.get("research_id", ""))
        tarih = clean_cell(row.get("baslangic_tarih", ""))
        saat = clean_cell(row.get("baslangic_saat", ""))
        bitis = compact_join([row.get("bitis_tarih", ""), row.get("bitis_saat", "")])
        mode = clean_cell(row.get("mode", ""))
        status = clean_cell(row.get("status", ""))
        fis_satiri = clean_cell(row.get("fis_satiri", ""))

        active_badge = " • AKTİF" if research_id == active_id else ""

        st.markdown(
            f"**{tarih} {saat} fiyat araştırması{active_badge}**  \n"
            f"{mode} • durum: {status} • kayıt satırı: {fis_satiri}"
        )

        if bitis:
            st.caption(f"Bitiş: {bitis}")

        render_research_preview_cards(research_id, limit=8)

        c1, c2, c3 = st.columns(3)

        if c1.button("Rotayı Göster", key=safe_key("open_research_route", research_id, i), use_container_width=True):
            st.session_state.compare_research_id = research_id
            st.session_state.route_excluded_products = []
            st.session_state.route_excluded_sources = []
            st.session_state.step = "compare_prices"
            st.rerun()

        if c2.button("Bu Araştırmaya Devam Et", key=safe_key("continue_research", research_id, i), use_container_width=True):
            continue_research_session(research_id)
            st.rerun()

        if c3.button("Sil", key=safe_key("delete_research", research_id, i), use_container_width=True):
            delete_research_session(research_id)
            st.success("Fiyat araştırması silindi.")
            st.rerun()

        st.divider()



def render_compare_screen():
    st.subheader("📊 En Ucuz / Rota")

    if st.button("⬅️ Ürünlere Dön", use_container_width=True):
        st.session_state.step = "product_tree"
        st.rerun()

    saved_all_df = read_saved_price_records()

    if saved_all_df.empty:
        st.warning("Henüz geçmiş fiyat kaydı yok. Birkaç fiş kaydettikten sonra karşılaştırma çalışır.")
        return

    st.markdown("#### Araştırmalar")
    research_id = render_research_history_nav()

    if not research_id:
        st.warning("Araştırma bulunamadı.")
        return

    ca, cb, cc = st.columns(3)

    if ca.button("Bu Araştırmaya Devam Et", use_container_width=True, key="compare_continue_research"):
        continue_research_session(research_id)
        st.rerun()

    if cb.button("Tüm Araştırmaları Gör", use_container_width=True, key="compare_all_research"):
        st.session_state.step = "research_history"
        st.rerun()

    if cc.button("Bu Araştırmayı Sil", use_container_width=True, key="compare_delete_research"):
        delete_research_session(research_id)
        st.success("Fiyat araştırması silindi.")
        st.session_state.step = "research_history"
        st.rerun()

    if "research_id" in saved_all_df.columns:
        saved_df = saved_all_df[saved_all_df["research_id"] == research_id].copy()
    else:
        saved_df = saved_all_df.copy()

    if saved_df.empty:
        st.warning("Bu fiyat araştırması için kayıtlı fiş bulunamadı.")
        return

    # En Ucuz/Rota ekranı seçili fiyat araştırmasındaki TÜM kayıtlı fişleri karşılaştırır.
    # Ekranda açık duran yeni/boş fiş buraya karışmaz.
    current_df = make_research_products_df(saved_df)

    if current_df.empty:
        st.info("Bu araştırma içinde en az bir kayıtlı fiş olmalı.")
        return

    excluded_sources = set(st.session_state.get("route_excluded_sources", []))
    excluded_products = set(st.session_state.get("route_excluded_products", []))

    if excluded_sources:
        saved_df = saved_df[~saved_df["source_name"].astype(str).isin(excluded_sources)].copy()

    if excluded_products and not current_df.empty:
        current_df = current_df[~current_df["product_id"].astype(str).isin(excluded_products)].copy()

    cheapest_df, stop_df, single_stop_df = compute_cheapest_plan(current_df, saved_df)

    if cheapest_df.empty:
        st.warning("Fişteki ürünler için geçmiş fiyat bulunamadı. Aynı ürünlerden fiyat kaydı yaptıkça öneri oluşacak.")
        return

    total_mixed = round(float(cheapest_df["en_ucuz_fiyat"].sum()), 2)
    total_saving = round(float(cheapest_df["tasarruf"].sum()), 2)
    found_count = len(cheapest_df)
    total_count = len(current_df)
    stop_count = cheapest_df["source_name"].nunique()

    st.markdown(f"### En ucuz toplam: {format_price(str(total_mixed))} ₺")
    st.success(f"Tahmini toplam tasarruf: {format_price(str(total_saving))} ₺")
    st.caption(f"{found_count} / {total_count} ürün • {stop_count} durak")

    if st.button("🛒 Alışverişe Başla", use_container_width=True, type="primary"):
        shopping_id = get_or_create_shopping_plan(cheapest_df, research_id)
        st.session_state.current_shopping_id = shopping_id
        load_shopping_checked_from_plan(shopping_id)
        st.session_state.step = "shopping_mode"
        st.rerun()

    st.markdown("---")
    st.markdown("## Rota bölümleri")
    st.caption("Neyi nereden alacağını kaynak kaynak gösterir.")

    render_route_cards(cheapest_df, shopping_mode=False, research_id=research_id)

    if not single_stop_df.empty:
        with st.expander("Tek durak alternatifi"):
            best_single = single_stop_df.iloc[0]
            st.success(
                f"{best_single['source_name']} • "
                f"{int(best_single['bulunan_urun'])}/{int(best_single['toplam_urun'])} ürün • "
                f"Toplam: {format_price(str(best_single['toplam']))} ₺"
            )

            for _, row in single_stop_df.head(10).iterrows():
                st.markdown(
                    f"**{row['source_name']}** — "
                    f"{int(row['bulunan_urun'])}/{int(row['toplam_urun'])} ürün, "
                    f"eksik: {int(row['eksik_urun'])}, "
                    f"toplam: {format_price(str(row['toplam']))} ₺"
                )

    st.markdown("---")
    st.caption("Not: Bu öneri sadece seçili fiyat araştırmasındaki kayıtlara göre çalışır.")





# =========================================================
# 12. SABİT ALT MENÜ
# =========================================================

def render_fixed_bottom_nav():
    if st.session_state.step == "location":
        return

    st.markdown('<div class="bottom-spacer"></div>', unsafe_allow_html=True)

    st.markdown('<div class="fixed-bottom-nav">', unsafe_allow_html=True)

    b1, b2, b3 = st.columns(3)

    if b1.button("🏠 Ana Menü", use_container_width=True, key="bottom_home"):
        st.session_state.step = "research_start"
        st.rerun()

    if b2.button("📊 En Ucuz / Rota", use_container_width=True, key="bottom_compare"):
        # Alışveriş modunda rota tekrarına düşmesin; kullanıcıyı ana akışa al.
        if st.session_state.step == "shopping_mode":
            st.session_state.step = "research_start"
        else:
            st.session_state.step = "compare_prices"
        st.rerun()

    if st.session_state.get("research_active", False):
        if b3.button("🏁 Araştırmayı Bitir", use_container_width=True, key="bottom_finish_research"):
            finish_research_session()
            st.rerun()
    else:
        if b3.button("🧾 Listeler", use_container_width=True, key="bottom_shopping_history"):
            st.session_state.step = "shopping_history"
            st.rerun()

    st.markdown('</div>', unsafe_allow_html=True)


# =========================================================
# 11. ANA ROUTER
# =========================================================

if products_df.empty:
    st.error("products_master_clean.csv bulunamadı veya boş.")
    st.stop()

if st.session_state.step == "location":
    render_location_screen()

elif st.session_state.step == "research_start":
    render_research_start_screen()

elif st.session_state.step == "source_smart":
    render_smart_source_screen()

elif st.session_state.step == "user_list_builder":
    render_user_list_builder_screen()

elif st.session_state.step == "user_lists":
    render_user_lists_screen()

elif st.session_state.step == "source_type":
    render_source_type_screen()

elif st.session_state.step == "source_name":
    render_source_name_screen()

elif st.session_state.step == "product_tree":
    render_product_tree_screen()

elif st.session_state.step == "price_entry":
    render_price_entry_screen()

elif st.session_state.step == "research_history":
    render_research_history_screen()

elif st.session_state.step == "compare_prices":
    render_compare_screen()

elif st.session_state.step == "shopping_mode":
    render_shopping_mode_screen()

elif st.session_state.step == "pending_shopping":
    render_pending_shopping_screen()

elif st.session_state.step == "shopping_history":
    render_shopping_history_screen()

else:
    st.session_state.step = "location"
    st.rerun()

render_fixed_bottom_nav()
