import streamlit as st
import pandas as pd
import plotly.express as px
import os
import re
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

def get_col(row, candidates, default=""):
    for c in candidates:
        if c in row and pd.notna(row[c]):
            return row[c]
    return default

def format_ib_date(raw_val):
    s = str(raw_val).strip()
    if "." in s and s.replace(".", "").isdigit():
        s = s.split(".")[0]
    digits = re.sub(r"\D", "", s)
    if len(digits) >= 8:
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"
    return s

def calc_dte(exp_str, status_str):
    if str(status_str).strip() != "Offen":
        return None
    try:
        exp_dt = datetime.strptime(str(exp_str).strip()[:10], "%Y-%m-%d").date()
        return (exp_dt - date.today()).days
    except Exception:
        return None

def parse_captrader_csv(uploaded_csv, existing_df):
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
        parts = ticker_raw.split()
        ticker = parts[0].upper() if parts else ""
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

        if qty < 0 and open_close in ["O", "OPEN", "E", "NAN", ""]:
            opens.append(trade_obj)
        elif qty > 0 or open_close in ["C", "CLOSE", "S"]:
            closes.append(trade_obj)

    opens.sort(key=lambda x: x["date"])
    closes.sort(key=lambda x: x["date"])

    imported_rows = []
    current_max_id = int(existing_df["ID"].max()) if not existing_df.empty else 0
    today_str = str(date.today())

    for op in opens:
        current_max_id += 1
        strat = "Cash Secured Put (CSP)" if op["put_call"] == "P" else ("Covered Call (CC)" if op["put_call"] == "C" else "Option (Sonstige)")
        
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

st.sidebar.header("🏦 CapTrader Import")
clear_before_import = st.sidebar.checkbox("Vor Import alte Daten löschen", value=True)
ct_file = st.sidebar.file_uploader("CapTrader Flex-Query CSV hochladen", type=["csv"], key="ct_up")

if ct_file is not None:
    if st.sidebar.button("📥 CapTrader Trades übernehmen", type="primary", use_container_width=True):
        try:
            base_df = pd.DataFrame(columns=COLUMNS) if clear_before_import else st.session_state.trades_df
            new_ct_df, raw_preview = parse_captrader_csv(ct_file, base_df)
            if not new_ct_df.empty:
                updated_df = pd.concat([base_df, new_ct_df], ignore_index=True)
                save_trades(updated_df)
                st.sidebar.success(f"✅ {len(new_ct_df)} Trades importiert!")
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
    if st.sidebar.button("📂 Backup wiederherstellen", use_container_width=True):
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

df = st.session_state.trades_df.copy()

if not df.empty:
    df["Netto-GuV ($)"] = pd.to_numeric(df["Netto-GuV ($)"], errors="coerce").fillna(0.0)
    df["Gebühren ($)"] = pd.to_numeric(df["Gebühren ($)"], errors="coerce").fillna(0.0)
    df["Kontrakte"] = pd.to_numeric(df["Kontrakte"], errors="coerce").fillna(0).astype(int)

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

trade_count = len(df)
tab1, tab2, tab3 = st.tabs([
    f"📋 Alle Trades ({trade_count})",
    "➕ Neuen Trade eintragen",
    f"📈 Monatliche Auswertung ({trade_count})"
])

with tab1:
    if st.button("🗑️ Datenbank komplett leeren (Reset)"):
        save_trades(pd.DataFrame(columns=COLUMNS))
        st.rerun()

    if df.empty:
        st.info("Datenbank ist aktuell leer. Bitte lade links deine CapTrader CSV-Datei hoch.")
    else:
        display_df = df.copy()
