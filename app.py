import streamlit as st
import pandas as pd
import plotly.express as px
import os
from datetime import date, datetime

st.set_page_config(page_title="Stillhalter Trading-Tagebuch", layout="wide")
st.title("📓 Stillhalter Trading-Tagebuch & CapTrader-Importer")

DATA_FILE = "tagebuch_daten.csv"

COLUMNS = [
    "ID", "Eröffnungsdatum", "Ticker", "Strategie", "Kontrakte",
    "Strike", "Verfall", "Prämie pro Aktie", "Gebühren ($)",
    "Status", "Schließungsdatum", "Rückkauf pro Aktie",
    "Netto-GuV ($)", "Rendite auf Kapital (%)", "Notizen"
]

# ==========================================
# --- DATEN LADEN & SPEICHERN ---
# ==========================================
def load_trades():
    if os.path.exists(DATA_FILE):
        try:
            df = pd.read_csv(DATA_FILE)
            if set(COLUMNS).issubset(df.columns):
                return df
        except Exception:
            pass
    return pd.DataFrame(columns=COLUMNS)

def save_trades(df):
    st.session_state.trades_df = df
    df.to_csv(DATA_FILE, index=False)

if "trades_df" not in st.session_state:
    st.session_state.trades_df = load_trades()

# ==========================================
# --- INTELLIGENTER CAPTRADER PARSER ---
# ==========================================
def get_col(row, candidates, default=""):
    for c in candidates:
        if c in row and pd.notna(row[c]):
            return row[c]
    return default

def format_ib_date(raw_val):
    s = str(raw_val).split(";")[0].split(",")[0].strip()
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:]}"
    return s

def parse_captrader_csv(uploaded_csv):
    uploaded_csv.seek(0)
    sample = uploaded_csv.read(2048).decode("utf-8", errors="ignore")
    sep = ";" if sample.count(";") > sample.count(",") else ","
    uploaded_csv.seek(0)
    
    raw_df = pd.read_csv(uploaded_csv, sep=sep)
    raw_df.columns = [c.strip().strip('"') for c in raw_df.columns]

    opens = []
    closes = []

    for _, r in raw_df.iterrows():
        asset = str(get_col(r, ["AssetClass", "Anlageklasse"], "OPT")).strip().upper()
        if asset not in ["OPT", "OPTIONEN", "OPTIONS", ""]:
            continue

        qty_raw = str(get_col(r, ["Quantity", "Menge"], "0")).replace(",", ".")
        try:
            qty = float(qty_raw)
        except ValueError:
            continue

        if qty == 0:
            continue

        ticker_raw = str(get_col(r, ["UnderlyingSymbol", "Basiswert-Symbol", "Symbol"], "")).strip()
        ticker = ticker_raw.split()[0].upper() if ticker_raw else ""
        if not ticker or ticker in ["NAN", "SYMBOL", "UNDERLYINGSYMBOL"]:
            continue

        put_call = str(get_col(r, ["Put/Call", "Put/Call-Indikator"], "")).strip().upper()
        
        try:
            strike = float(str(get_col(r, ["Strike", "Ausübungspreis"], "0")).replace(",", "."))
            price = abs(float(str(get_col(r, ["TradePrice", "Handelspreis"], "0")).replace(",", ".")))
            comm = abs(float(str(get_col(r, ["IBCommission", "IB-Provision", "Gebühren"], "0")).replace(",", ".")))
        except ValueError:
            continue

        t_date = format_ib_date(get_col(r, ["TradeDate", "Handelsdatum"], str(date.today())))
        exp_date = format_ib_date(get_col(r, ["Expiry", "Verfallsdatum"], str(date.today())))
        open_close = str(get_col(r, ["Open/CloseIndicator", "Eröffnungs-/Schließungsindikator"], "")).strip().upper()

        trade_obj = {
            "ticker": ticker,
            "put_call": put_call[:1] if put_call else "",
            "strike": strike,
            "expiry": exp_date,
            "date": t_date,
            "contracts": int(abs(qty)),
            "price": price,
            "comm": comm,
            "used": False
        }

        # Unterscheidung: Short-Eröffnung vs. Rückkauf/Schließung
        if qty < 0 and open_close in ["O", "OPEN", "E", "NAN", ""]:
            opens.append(trade_obj)
        elif qty > 0 or open_close in ["C", "CLOSE", "S"]:
            closes.append(trade_obj)

    # Nach Datum sortieren, damit Zuordnung chronologisch stimmt
    opens.sort(key=lambda x: x["date"])
    closes.sort(key=lambda x: x["date"])

    imported_rows = []
    current_max_id = int(st.session_state.trades_df["ID"].max()) if not st.session_state.trades_df.empty else 0
    today_str = str(date.today())

    for op in opens:
        current_max_id += 1
        strat = "Cash Secured Put (CSP)" if op["put_call"] == "P" else ("Covered Call (CC)" if op["put_call"] == "C" else "Option (Sonstige)")
        
        # Passenden Rückkauf suchen (gleicher Ticker, Put/Call, Strike, Verfall)
        matched_close = None
        for cl in closes:
            if (not cl["used"] and cl["ticker"] == op["ticker"] and 
                cl["put_call"] == op["put_call"] and cl["strike"] == op["strike"] and 
                cl["expiry"] == op["expiry"] and cl["date"] >= op["date"]):
                matched_close = cl
                cl["used"] = True
                break

        if matched_close:
            status = "Vorzeitig zurückgekauft"
            close_date = matched_close["date"]
            buyback_price = matched_close["price"]
            total_comm = op["comm"] + matched_close["comm"]
            net_pnl = (op["contracts"] * 100 * (op["price"] - buyback_price)) - total_comm
        else:
            total_comm = op["comm"]
            buyback_price = 0.0
            # Prüfen, ob Verfallsdatum bereits vorbei ist
            if op["expiry"] < today_str:
                status = "Wertlos verfallen"
                close_date = op["expiry"]
            else:
                status = "Offen"
                close_date = "-"
            net_pnl = (op["contracts"] * 100 * op["price"]) - total_comm

        cap_req = op["contracts"] * 100 * op["strike"]
        roc = (net_pnl / cap_req * 100) if cap_req > 0 else 0.0

        imported_rows.append({
            "ID": current_max_id,
            "Eröffnungsdatum": op["date"],
            "Ticker": op["ticker"],
            "Strategie": strat,
            "Kontrakte": op["contracts"],
            "Strike": op["strike"],
            "Verfall": op["expiry"],
            "Prämie pro Aktie": round(op["price"], 3),
            "Gebühren ($)": round(total_comm, 2),
            "Status": status,
            "Schließungsdatum": close_date,
            "Rückkauf pro Aktie": round(buyback_price, 3),
            "Netto-GuV ($)": round(net_pnl, 2),
            "Rendite auf Kapital (%)": round(roc, 2),
            "Notizen": "CapTrader Import"
        })

    return pd.DataFrame(imported_rows), raw_df

# ==========================================
# --- SIDEBAR: BACKUP & CAPTRADER IMPORT ---
# ==========================================
st.sidebar.header("🏦 CapTrader Import")
ct_file = st.sidebar.file_uploader("CapTrader Flex-Query CSV hochladen", type=["csv"], key="ct_up")
if ct_file is not None:
    if st.sidebar.button("📥 CapTrader Trades übernehmen", type="primary"):
        try:
            new_ct_df, raw_preview = parse_captrader_csv(ct_file)
            if not new_ct_df.empty:
                updated_df = pd.concat([st.session_state.trades_df, new_ct_df], ignore_index=True)
                save_trades(updated_df)
                st.sidebar.success(f"✅ {len(new_ct_df)} Trades importiert & automatisch abgeglichen!")
                st.rerun()
            else:
                st.sidebar.warning("0 Short-Options-Eröffnungen gefunden.")
                st.dataframe(raw_preview.head(5))
        except Exception as e:
            st.sidebar.error(f"Fehler beim Import: {e}")

st.sidebar.divider()
st.sidebar.header("💾 Tagebuch-Backup (CSV)")

csv_data = st.session_state.trades_df.to_csv(index=False).encode("utf-8")
st.sidebar.download_button(
    label="⬇️ Tagebuch als CSV speichern",
    data=csv_data,
    file_name=f"stillhalter_tagebuch_{date.today()}.csv",
    mime="text/csv",
    use_container_width=True
)

uploaded_file = st.sidebar.file_uploader("⬆️ Gespeichertes Tagebuch laden", type=["csv"], key="bk_up")
if uploaded_file is not None:
    if st.sidebar.button("📂 Backup wiederherstellen"):
        try:
            loaded_df = pd.read_csv(uploaded_file)
            if set(COLUMNS).issubset(loaded_df.columns):
                save_trades(loaded_df)
                st.sidebar.success("Tagebuch geladen!")
                st.rerun()
            else:
                st.sidebar.error("Falsches Dateiformat.")
        except Exception as e:
            st.sidebar.error(f"Fehler: {e}")

# ==========================================
# --- KPI-ÜBERSICHT (KENNZAHLEN) ---
# ==========================================
df = st.session_state.trades_df

total_pnl = df["Netto-GuV ($)"].sum() if not df.empty else 0.0
open_trades = len(df[df["Status"] == "Offen"]) if not df.empty else 0
closed_df = df[df["Status"] != "Offen"] if not df.empty else pd.DataFrame()
win_rate = (len(closed_df[closed_df["Netto-GuV ($)"] > 0]) / len(closed_df) * 100) if len(closed_df) > 0 else 0.0
open_premium = df[df["Status"] == "Offen"]["Netto-GuV ($)"].sum() if not df.empty else 0.0

c1, c2, c3, c4 = st.columns(4)
c1.metric("💰 Gesamt-Gewinn / Verlust", f"{total_pnl:,.2f} $")
c2.metric("📂 Offene Positionen", f"{open_trades}")
c3.metric("⏳ Gebundene Prämie (Offen)", f"{open_premium:,.2f} $")
c4.metric("🎯 Trefferquote (Geschlossen)", f"{win_rate:.1f} %")

st.divider()

# ==========================================
# --- REITER: VERWALTUNG / NEUER TRADE / CHART ---
# ==========================================
tab1, tab2, tab3 = st.tabs(["📋 Alle Trades & Schließen", "➕ Neuen Trade eintragen", "📈 Auswertung"])

with tab1:
    if df.empty:
        st.info("Noch keine Trades vorhanden. Importiere links deine CapTrader CSV-Datei oder trage einen Trade unter 'Neuen Trade eintragen' ein.")
    else:
        st.subheader("Aktuelle Übersicht")
        st.dataframe(df, hide_index=True, use_container_width=True)

