import streamlit as st
import pandas as pd
import plotly.express as px
import os
import re
from datetime import date, datetime

st.set_page_config(page_title="Stillhalter Trading-Tagebuch", layout="wide")
st.title("📓 Stillhalter Trading-Tagebuch")
st.link_button("📊 Zum Stillhalter-Screener wechseln", "https://stillhalterscreener.streamlit.app/")


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

def to_float(val):
    try:
        s = str(val).strip().replace('"', '').replace(",", ".")
        return 0.0 if s in ["", "nan", "NaN"] else float(s)
    except Exception:
        return 0.0

def format_ib_date(raw_val):
    digits = re.sub(r"\D", "", str(raw_val))
    return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}" if len(digits) >= 8 else str(raw_val).strip()

def calc_dte(exp_str, status_str):
    if str(status_str).strip() != "Offen":
        return None
    try:
        return (datetime.strptime(str(exp_str).strip()[:10], "%Y-%m-%d").date() - date.today()).days
    except Exception:
        return None

def parse_captrader_csv(uploaded_csv, existing_df):
    uploaded_csv.seek(0)
    sample = uploaded_csv.read(2048).decode("utf-8", errors="ignore")
    sep = ";" if sample.count(";") > sample.count(",") else ","
    uploaded_csv.seek(0)
    
    raw_df = pd.read_csv(uploaded_csv, sep=sep, dtype=str).fillna("")
    raw_df.columns = [c.strip().strip('"') for c in raw_df.columns]

    opens, closes = [], []
    stk_count, opt_count = 0, 0

    for _, r in raw_df.iterrows():
        asset = str(r.get("AssetClass", r.get("Anlageklasse", ""))).strip().upper()
        if asset == "STK":
            stk_count += 1
            continue
        if asset not in ["OPT", "OPTIONEN", "OPTIONS", ""]:
            continue

        qty = to_float(r.get("Quantity", r.get("Menge", "0")))
        if qty == 0:
            continue

        opt_count += 1
        ticker = str(r.get("UnderlyingSymbol", r.get("Basiswert-Symbol", r.get("Symbol", "")))).strip().upper()
        if not ticker or ticker in ["NAN", "SYMBOL", "UNDERLYINGSYMBOL"]:
            continue

        put_call = str(r.get("Put/Call", r.get("Put/Call-Indikator", ""))).strip().upper()
        strike = to_float(r.get("Strike", r.get("Ausübungspreis", "0")))
        price = abs(to_float(r.get("TradePrice", r.get("Handelspreis", "0"))))
        comm = abs(to_float(r.get("IBCommission", r.get("IB-Provision", r.get("Gebühren", "0")))))
        t_date = format_ib_date(r.get("TradeDate", r.get("Handelsdatum", str(date.today()))))
        exp_date = format_ib_date(r.get("Expiry", r.get("Verfallsdatum", str(date.today()))))
        oc = str(r.get("Open/CloseIndicator", r.get("Eröffnungs-/Schließungsindikator", ""))).strip().upper()

        obj = {"ticker": ticker, "pc": put_call[:1], "strike": strike, "exp": exp_date, "date": t_date, "qty": int(abs(qty)), "price": price, "comm": comm, "used": False}
        if qty < 0 and oc in ["O", "OPEN", "E", "NAN", ""]:
            opens.append(obj)
        elif qty > 0 or oc in ["C", "CLOSE", "S"]:
            closes.append(obj)

    opens.sort(key=lambda x: x["date"])
    closes.sort(key=lambda x: x["date"])

    rows = []
    max_id = int(existing_df["ID"].max()) if not existing_df.empty else 0
    today_str = str(date.today())

    for op in opens:
        max_id += 1
        strat = "Cash Secured Put (CSP)" if op["pc"] == "P" else ("Covered Call (CC)" if op["pc"] == "C" else "Option")
        match = next((cl for cl in closes if not cl["used"] and cl["ticker"] == op["ticker"] and cl["pc"] == op["pc"] and cl["strike"] == op["strike"] and cl["exp"] == op["exp"] and cl["date"] >= op["date"]), None)
        
        if match:
            match["used"] = True
            status, c_date, bb, comm = "Vorzeitig zurückgekauft", match["date"], match["price"], op["comm"] + match["comm"]
            pnl = (op["qty"] * 100 * (op["price"] - bb)) - comm
        else:
            comm, bb = op["comm"], 0.0
            status = "Wertlos verfallen" if op["exp"] < today_str else "Offen"
            c_date = op["exp"] if op["exp"] < today_str else "-"
            pnl = (op["qty"] * 100 * op["price"]) - comm

        cap = op["qty"] * 100 * op["strike"]
        roc = (pnl / cap * 100) if cap > 0 else 0.0
        rows.append({
            "ID": max_id, "Eröffnungsdatum": op["date"], "Ticker": op["ticker"], "Strategie": strat,
            "Kontrakte": op["qty"], "Strike": op["strike"], "Verfall": op["exp"], "Prämie pro Aktie": round(op["price"], 3),
            "Gebühren ($)": round(comm, 2), "Status": status, "Schließungsdatum": c_date, "Rückkauf pro Aktie": round(bb, 3),
            "Netto-GuV ($)": round(pnl, 2), "Rendite auf Kapital (%)": round(roc, 2), "Notizen": "CapTrader Import"
        })

    return pd.DataFrame(rows), f"Gelesen: {len(raw_df)} Zeilen ({opt_count} OPT, {stk_count} STK)."

st.sidebar.header("🏦 CapTrader Import")
clear_old = st.sidebar.checkbox("Vor Import alte Daten löschen", value=True)
ct_file = st.sidebar.file_uploader("CapTrader CSV hochladen", type=["csv"])

if ct_file and st.sidebar.button("📥 Trades übernehmen", type="primary", use_container_width=True):
    base = pd.DataFrame(columns=COLUMNS) if clear_old else st.session_state.trades_df
    new_df, info = parse_captrader_csv(ct_file, base)
    st.sidebar.info(info)
    if not new_df.empty:
        save_trades(pd.concat([base, new_df], ignore_index=True))
        st.sidebar.success(f"✅ {len(new_df)} Trades importiert!")

st.sidebar.divider()
st.sidebar.download_button("⬇️ Backup speichern (CSV)", st.session_state.trades_df.to_csv(index=False).encode("utf-8"), f"tagebuch_{date.today()}.csv", "text/csv", use_container_width=True)
bk_file = st.sidebar.file_uploader("⬆️ Backup laden", type=["csv"], key="bk")
if bk_file and st.sidebar.button("📂 Backup wiederherstellen", use_container_width=True):
    save_trades(pd.read_csv(bk_file))
    st.sidebar.success("Geladen!")

df = st.session_state.trades_df.copy()
if not df.empty:
    df["Netto-GuV ($)"] = pd.to_numeric(df["Netto-GuV ($)"], errors="coerce").fillna(0.0)
    df["Gebühren ($)"] = pd.to_numeric(df["Gebühren ($)"], errors="coerce").fillna(0.0)
    df["Kontrakte"] = pd.to_numeric(df["Kontrakte"], errors="coerce").fillna(0).astype(int)

c1, c2, c3, c4 = st.columns(4)
c1.metric("💰 Gesamt-GuV", f"{df['Netto-GuV ($)'].sum() if not df.empty else 0.0:,.2f} $")
c2.metric("📂 Offene Positionen", f"{len(df[df['Status'] == 'Offen']) if not df.empty else 0}")
c3.metric("⏳ Gebundene Prämie", f"{df[df['Status'] == 'Offen']['Netto-GuV ($)'].sum() if not df.empty else 0.0:,.2f} $")
closed = df[df["Status"] != "Offen"] if not df.empty else pd.DataFrame()
c4.metric("🎯 Trefferquote", f"{(len(closed[closed['Netto-GuV ($)'] > 0]) / len(closed) * 100) if len(closed) > 0 else 0.0:.1f} %")

st.divider()
ansicht = st.radio("Ansicht:", [f"📋 Alle Trades ({len(df)})", f"📈 Monatliche Auswertung ({len(df)})"], horizontal=True)

if ansicht.startswith("📋"):
    if st.button("🗑️ Datenbank leeren (Reset)"):
        save_trades(pd.DataFrame(columns=COLUMNS))
        st.rerun()
    if df.empty:
        st.info("Datenbank ist leer. Lade links deine CapTrader CSV-Datei hoch.")
    else:
        disp = df.copy()
        dtes = [calc_dte(r["Verfall"], r["Status"]) for _, r in disp.iterrows()]
        disp.insert(7, "Restlaufzeit", ["-" if d is None else (f"⚠️ {d} Tage" if d < 10 else f"{d} Tage") for d in dtes])
        warn = [f"{disp.iloc[i]['Ticker']} ({d}T)" for i, d in enumerate(dtes) if d is not None and d < 10]
        if warn:
            st.error("🚨 **Verfall < 10 Tage:** " + " | ".join(warn))
        st.dataframe(disp.style.apply(lambda r: ["background-color: rgba(255,75,75,0.25); font-weight: bold"]*len(r) if "⚠️" in str(r["Restlaufzeit"]) else [""]*len(r), axis=1), hide_index=True, use_container_width=True, height=600)

if ansicht.startswith("📈"):
    if df.empty:
        st.warning("Noch keine Trades geladen. Bitte importiere links deine CSV-Datei.")
    else:
        df["Monat"] = df["Eröffnungsdatum"].astype(str).str.slice(0, 7)
        m_sum = df.groupby("Monat", as_index=False).agg(Trades=("ID", "count"), Kontrakte=("Kontrakte", "sum"), Gebühren=("Gebühren ($)", "sum"), Netto_GuV=("Netto-GuV ($)", "sum")).sort_values("Monat")
        st.subheader("📅 Monatliche Performance-Übersicht")
        fig = px.bar(m_sum, x="Monat", y="Netto_GuV", text_auto=".2f", title="Netto-Gewinn / Verlust pro Monat ($)", template="plotly_dark", color="Netto_GuV", color_continuous_scale="RdYlGn")
        fig.update_layout(xaxis_type="category")
        st.plotly_chart(fig, use_container_width=True)
        st.dataframe(m_sum, hide_index=True, use_container_width=True)
