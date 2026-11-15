import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import date, datetime

st.set_page_config(page_title="Stillhalter Trading-Tagebuch", layout="wide")
st.title("📓 Stillhalter Trading-Tagebuch & CapTrader-Importer")

# ==========================================
# --- DATENSPEICHER INITIALISIEREN ---
# ==========================================
COLUMNS = [
    "ID", "Eröffnungsdatum", "Ticker", "Strategie", "Kontrakte",
    "Strike", "Verfall", "Prämie pro Aktie", "Gebühren ($)",
    "Status", "Schließungsdatum", "Rückkauf pro Aktie",
    "Netto-GuV ($)", "Rendite auf Kapital (%)", "Notizen"
]

if "trades_df" not in st.session_state:
    st.session_state.trades_df = pd.DataFrame(columns=COLUMNS)

# ==========================================
# --- CAPTRADER CSV PARSER ---
# ==========================================
def parse_captrader_csv(uploaded_csv):
    raw_df = pd.read_csv(uploaded_csv)
    # Nur Options-Trades herausfiltern (falls Aktien dabei sind)
    if "AssetClass" in raw_df.columns:
        raw_df = raw_df[raw_df["AssetClass"] == "OPT"]
    
    imported_rows = []
    current_max_id = int(st.session_state.trades_df["ID"].max()) if not st.session_state.trades_df.empty else 0

    for _, r in raw_df.iterrows():
        qty = float(r.get("Quantity", 0))
        # Wir importieren primär Verkäufe (Short-Eröffnungen: Quantity < 0)
        if qty == 0:
            continue

        ticker = str(r.get("UnderlyingSymbol", r.get("Symbol", ""))).split()[0].upper()
        put_call = str(r.get("Put/Call", "")).upper()
        strike = float(r.get("Strike", 0))
        
        # Datum formatieren
        raw_date = str(r.get("TradeDate", date.today())).split(";")[0].split(",")[0]
        if len(raw_date) == 8 and raw_date.isdigit(): # Format YYYYMMDD
            open_date = f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:]}"
        else:
            open_date = raw_date

        raw_exp = str(r.get("Expiry", date.today()))
        if len(raw_exp) == 8 and raw_exp.isdigit():
            exp_date = f"{raw_exp[:4]}-{raw_exp[4:6]}-{raw_exp[6:]}"
        else:
            exp_date = raw_exp

        price = abs(float(r.get("TradePrice", 0)))
        comm = abs(float(r.get("IBCommission", 0)))
        contracts = int(abs(qty))
        open_close = str(r.get("Open/CloseIndicator", "O")).upper()

        # Strategie bestimmen
        if put_call == "P":
            strat = "Cash Secured Put (CSP)"
        elif put_call == "C":
            strat = "Covered Call (CC)"
        else:
            strat = "Option (Sonstige)"

        # Nur Eröffnungen (Open) als neue Trades anlegen
        if qty < 0 and open_close in ["O", "OPEN", "NAN", ""]:
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

    return pd.DataFrame(imported_rows)

# ==========================================
# --- SIDEBAR: BACKUP & CAPTRADER IMPORT ---
# ==========================================
st.sidebar.header("🏦 CapTrader Import")
ct_file = st.sidebar.file_uploader("CapTrader Flex-Query CSV hochladen", type=["csv"], key="ct_up")
if ct_file is not None:
    if st.sidebar.button("📥 CapTrader Trades übernehmen", type="primary"):
        try:
            new_ct_df = parse_captrader_csv(ct_file)
            if not new_ct_df.empty:
                st.session_state.trades_df = pd.concat([st.session_state.trades_df, new_ct_df], ignore_index=True)
                st.sidebar.success(f"{len(new_ct_df)} Trades erfolgreich von CapTrader importiert!")
                st.rerun()
            else:
                st.sidebar.warning("Keine neuen Short-Options-Eröffnungen in der Datei gefunden.")
        except Exception as e:
            st.sidebar.error(f"Fehler beim CapTrader-Import: {e}")

st.sidebar.divider()
st.sidebar.header("💾 Tagebuch-Backup (CSV)")

# Export
csv_data = st.session_state.trades_df.to_csv(index=False).encode("utf-8")
st.sidebar.download_button(
    label="⬇️ Tagebuch als CSV speichern",
    data=csv_data,
    file_name=f"stillhalter_tagebuch_{date.today()}.csv",
    mime="text/csv",
    use_container_width=True
)

# Import Backup
uploaded_file = st.sidebar.file_uploader("⬆️ Gespeichertes Tagebuch laden", type=["csv"], key="bk_up")
if uploaded_file is not None:
    if st.sidebar.button("📂 Backup wiederherstellen"):
        try:
            loaded_df = pd.read_csv(uploaded_file)
            if set(COLUMNS).issubset(loaded_df.columns):
                st.session_state.trades_df = loaded_df
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
tab1, tab2, tab3 = st.tabs(["➕ Neuen Trade eintragen", "📋 Alle Trades & Schließen", "📈 Auswertung"])

with tab1:
    with st.form("new_trade_form", clear_on_submit=True):
        col1, col2, col3 = st.columns(3)
        
        with col1:
            t_open_date = st.date_input("Eröffnungsdatum", value=date.today())
            t_ticker = st.text_input("Ticker-Symbol (z. B. AAPL, AAL)").upper().strip()
            t_strategy = st.selectbox("Strategie", ["Cash Secured Put (CSP)", "Covered Call (CC)", "Bull Put Spread", "Bear Call Spread", "Iron Condor"])
        
        with col2:
            t_contracts = st.number_input("Anzahl Kontrakte", min_value=1, value=1, step=1)
            t_strike = st.number_input("Strike-Preis ($)", min_value=0.5, value=50.0, step=0.5)
            t_exp_date = st.date_input("Verfallsdatum", value=date.today())
            
        with col3:
            t_premium = st.number_input("Erhaltene Prämie pro Aktie ($)", min_value=0.01, value=1.20, step=0.05)
            t_fees = st.number_input("Gebühren gesamt ($)", min_value=0.0, value=2.50, step=0.5)
            t_notes = st.text_input("Notiz / Setup (z. B. Entry Score 75%, HV Rank 60%)")

        submitted = st.form_submit_button("✅ Trade ins Tagebuch eintragen", type="primary")
        
        if submitted:
            if not t_ticker:
                st.error("Bitte gib ein Ticker-Symbol ein.")
            else:
                gross_premium = t_contracts * 100 * t_premium
                net_pnl = gross_premium - t_fees
                capital_req = t_contracts * 100 * t_strike
                roc = (net_pnl / capital_req * 100) if capital_req > 0 else 0.0
                new_id = int(df["ID"].max() + 1) if not df.empty else 1

                new_row = pd.DataFrame([{
                    "ID": new_id,
                    "Eröffnungsdatum": str(t_open_date),
                    "Ticker": t_ticker,
                    "Strategie": t_strategy,
                    "Kontrakte": t_contracts,
                    "Strike": t_strike,
                    "Verfall": str(t_exp_date),
                    "Prämie pro Aktie": t_premium,
                    "Gebühren ($)": t_fees,
                    "Status": "Offen",
                    "Schließungsdatum": "-",
                    "Rückkauf pro Aktie": 0.0,
                    "Netto-GuV ($)": round(net_pnl, 2),
                    "Rendite auf Kapital (%)": round(roc, 2),
                    "Notizen": t_notes
                }])
                st.session_state.trades_df = pd.concat([st.session_state.trades_df, new_row], ignore_index=True)
                st.success(f"Trade für {t_ticker} eingetragen! Netto-Prämie: {net_pnl:.2f} $")
                st.rerun()

with tab2:
    if df.empty:
        st.info("Noch keine Trades vorhanden. Trage einen Trade ein oder importiere deine CapTrader CSV-Datei links.")
    else:
        st.subheader("Aktuelle Übersicht")
        st.dataframe(df, hide_index=True, use_container_width=True)

        st.subheader("🔄 Offenen Trade schließen / abrechnen")
        open_list = df[df["Status"] == "Offen"]
        
        if open_list.empty:
            st.write("Aktuell sind keine offenen Trades vorhanden.")
        else:
            c_sel, c_stat, c_buyback, c_date = st.columns(4)
