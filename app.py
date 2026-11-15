import streamlit as st
import pandas as pd
import plotly.express as px
import os
from datetime import date

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
# --- FLEXIBLER CAPTRADER PARSER (DE & EN) ---
# ==========================================
def get_col(row, candidates, default=""):
    for c in candidates:
        if c in row and pd.notna(row[c]):
            return row[c]
    return default

def parse_captrader_csv(uploaded_csv):
    # Trennzeichen automatisch erkennen (, oder ;)
    uploaded_csv.seek(0)
    sample = uploaded_csv.read(2048).decode("utf-8", errors="ignore")
    sep = ";" if sample.count(";") > sample.count(",") else ","
    uploaded_csv.seek(0)
    
    raw_df = pd.read_csv(uploaded_csv, sep=sep)
    
    # Spaltennamen bereinigen
    raw_df.columns = [c.strip().strip('"') for c in raw_df.columns]

    imported_rows = []
    current_max_id = int(st.session_state.trades_df["ID"].max()) if not st.session_state.trades_df.empty else 0

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

        # Datum formatieren
        raw_date = str(get_col(r, ["TradeDate", "Handelsdatum"], str(date.today()))).split(";")[0].split(",")[0].strip()
        if len(raw_date) == 8 and raw_date.isdigit():
            open_date = f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:]}"
        else:
            open_date = raw_date

        raw_exp = str(get_col(r, ["Expiry", "Verfallsdatum"], str(date.today()))).strip()
        if len(raw_exp) == 8 and raw_exp.isdigit():
            exp_date = f"{raw_exp[:4]}-{raw_exp[4:6]}-{raw_exp[6:]}"
        else:
            exp_date = raw_exp

        contracts = int(abs(qty))
        open_close = str(get_col(r, ["Open/CloseIndicator", "Eröffnungs-/Schließungsindikator"], "O")).strip().upper()

        if put_call.startswith("P"):
            strat = "Cash Secured Put (CSP)"
        elif put_call.startswith("C"):
            strat = "Covered Call (CC)"
        else:
            strat = "Option (Sonstige)"

        # Verkäufe (Short-Eröffnungen) übernehmen
        if qty < 0 and open_close in ["O", "OPEN", "E", "NAN", ""]:
            current_max_id += 1
            gross_prem = contracts * 100 * price
            net_pnl = gross_prem - comm
            cap_req = contracts * 100 * strike
            roc = (net_pnl / cap_req * 100) if cap_req > 0 else 0.0

            imported_rows.append({
                "ID": current_max_id,
                "Eröffnungsdatum": open_date,
                "Ticker": ticker,
                "Strategie": strat,
                "Kontrakte": contracts,
                "Strike": strike,
                "Verfall": exp_date,
                "Prämie pro Aktie": round(price, 3),
                "Gebühren ($)": round(comm, 2),
                "Status": "Offen",
                "Schließungsdatum": "-",
                "Rückkauf pro Aktie": 0.0,
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
                st.sidebar.success(f"✅ {len(new_ct_df)} Trades importiert & gespeichert!")
                st.rerun()
            else:
                st.sidebar.warning("0 Short-Options-Eröffnungen gefunden. Prüfe die Vorschau unten.")
                st.write("### 🔍 Vorschau deiner hochgeladenen CapTrader-Datei (erste 5 Zeilen):")
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
# --- REITER: NEUER TRADE / VERWALTUNG / CHART ---
# ==========================================
tab1, tab2, tab3 = st.tabs(["📋 Alle Trades & Schließen", "➕ Neuen Trade eintragen", "📈 Auswertung"])

with tab1:
    if df.empty:
        st.info("Noch keine Trades vorhanden. Importiere links deine CapTrader CSV-Datei oder trage einen Trade unter 'Neuen Trade eintragen' ein.")
    else:
        st.subheader("Aktuelle Übersicht")
        st.dataframe(df, hide_index=True, use_container_width=True)

        st.subheader("🔄 Offenen Trade schließen / abrechnen")
        open_list = df[df["Status"] == "Offen"]
        
        if open_list.empty:
            st.write("Aktuell sind keine offenen Trades vorhanden.")
        else:
            c_sel, c_stat, c_buyback, c_date = st.columns(4)
            trade_options = {f"ID {row['ID']} | {row['Ticker']} {row['Strategie']} (Strike {row['Strike']})": row["ID"] for _, row in open_list.iterrows()}
            
            selected_label = c_sel.selectbox("Trade auswählen", list(trade_options.keys()))
            selected_id = trade_options[selected_label]
            
            close_status = c_stat.selectbox("Ergebnis", ["Wertlos verfallen", "Vorzeitig zurückgekauft", "Angedient (Assigned)"])
            buyback_price = c_buyback.number_input("Rückkaufpreis pro Aktie ($)", min_value=0.0, value=0.0, step=0.05)
            close_date = c_date.date_input("Schließungsdatum", value=date.today())

            if st.button("💾 Trade-Abschluss speichern"):
                idx = df[df["ID"] == selected_id].index
                contracts = df.loc[idx, "Kontrakte"]
                open_prem = df.loc[idx, "Prämie pro Aktie"]
                fees = df.loc[idx, "Gebühren ($)"]
                strike = df.loc[idx, "Strike"]

