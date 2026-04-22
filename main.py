import streamlit as st
import pandas as pd
import json
import os
from datetime import datetime

# Dosya Yolları
DATA_FILE = 'data.json'
MASTER_DATA_FILE = 'FiyatCep_MasterData_Sadelestirilmis_v2.xlsx - MasterData.csv'

st.set_page_config(page_title="FiyatCep", page_icon="🛒")
st.title("🛒 FiyatCep: Tasarruf Asistanı")

# Master Veriyi Yükle
@st.cache_data
def load_master_data():
    try:
        df = pd.read_csv(MASTER_DATA_FILE)
        return df
    except:
        return pd.DataFrame(columns=["Kategori", "Ürün Adı"])

master_df = load_master_data()

# Veri Saklama Fonksiyonları
def save_price(market, category, product, price):
    new_entry = {
        "tarih": datetime.now().strftime("%Y-%m-%d"),
        "market": market,
        "kategori": category,
        "urun": product,
        "fiyat": float(price)
    }
    data = []
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
    data.append(new_entry)
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

# --- ARAYÜZ (Görsel Taslağınız) ---
tab1, tab2 = st.tabs(["Fiyat Girişi", "En Ucuz Rota"])

with tab1:
    st.subheader("Ürün Kaydet")
    market = st.text_input("Market Adı", placeholder="Örn: Migros")
    
    category = st.selectbox("Kategori Seçin", master_df["Kategori"].unique())
    products = master_df[master_df["Kategori"] == category]["Ürün Adı"].tolist()
    product = st.selectbox("Ürün Seçin", products)
    
    price = st.number_input("Fiyat (TL)", min_value=0.0, step=0.5)
    
    if st.button("Kaydet ve Devam Et"):
        save_price(market, category, product, price)
        st.success(f"{product} başarıyla kaydedildi!")

with tab2:
    st.subheader("📍 Optimum Alışveriş Rotası")
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        if data:
            df_prices = pd.DataFrame(data)
            # Her ürün için en ucuz marketi bul
            idx = df_prices.groupby('urun')['fiyat'].idxmin()
            cheapest_items = df_prices.loc[idx]
            
            st.table(cheapest_items[['urun', 'market', 'fiyat']])
            st.metric("Toplam Tasarruflu Tutar", f"{cheapest_items['fiyat'].sum()} TL")
        else:
            st.info("Henüz veri girilmemiş.")
        