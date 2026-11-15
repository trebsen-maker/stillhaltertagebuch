import streamlit as st
import pandas as pd
from datetime import date, datetime
import io

st.set_page_config(page_title="Stillhalter Trading-Tagebuch", page_icon="📒", layout="wide")

# ==========================================
# --- DATENINITIALISIERUNG (SESSION STATE) ---
# ==========================================
COLUMNS = [
    "ID", "Eröffnet am", "Ticker", "Strategie", "Kontrakte", "Strike",
    "Verfall", "Prämie/Aktie", "Rückkauf/Aktie", "Gebühren", "Status",
    "Netto G&V", "Kapitalbindung", "Notiz"
]

if "trades_df" not in st.session_state:
    # Beispiel-Daten für den direkten Start (können einfach gelöscht werden)
    sample_data = [
        {
            "ID": 1, "Eröffnet am": date(2026, 11, 2), "Ticker": "AAPL", "Strategie": "CSP",
            "Kontrakte": 1, "Strike": 220.0, "Verfall": date(2026, 12, 18),
            "Prämie/Aktie": 3.40, "Rückkauf/Aktie": 0.0, "Gebühren": 2.50,
            "Status": "Offen", "Netto G&V": 337.50, "Kapitalbindung": 22000.0, "Notiz": "HV Rank > 40"
        },
        {
            "ID": 2, "Eröffnet am": date(2026, 10, 15), "Ticker": "AAL", "Strategie": "CC",
            "Kontrakte": 2, "Strike": 15.0, "Verfall": date(2026, 11, 13),
            "Prämie/Aktie": 0.55, "Rückkauf/Aktie": 0.10, "Gebühren": 4.00,
            "Status": "Zurückgekauft", "Netto G&V": 86.00, "Kapitalbindung": 0.0, "Notiz": "80% Gewinn mitgenommen"
        }
    ]
    st.session_state.trades_df = pd.DataFrame(sample_data)

def recalculate_df(df):
    if df.empty:
        return df
    df = df.copy()
    # Multiplikator 100 pro Optionskontrakt
    gross_in = df["Kontrakte"] * 100 * df["Prämie/Aktie"]
    gross_out = df["Kontrakte"] * 100 * df["Rückkauf/Aktie"]
    df["Netto G&V"] = (gross_in - gross_out - df["Gebühren"]).round(2)
    
    # Kapitalbindung: Bei offenen CSPs = Strike * 100 * Kontrakte, sonst 0
    df["Kapitalbindung"] = df.apply(
        lambda r: round(r["Strike"] * 100 * r["Kontrakte"], 2) if (r["Strategie"] == "CSP" and r["Status"] == "Offen") else 0.0,
        axis=1
    )
    return df

st.session_state.trades_df = recalculate_df(st.session_state.trades_df)
df = st.session_state.trades_df

# ==========================================
# --- KOPFZEILE & GESAMTÜBERSICHT (SALDEN) ---
# ==========================================
st.title("📒 Stillhalter Trading-Tagebuch (CSP & CC)")

realized_df = df[df["Status"] != "Offen"]
open_df = df[df["Status"] == "Offen"]

total_net_pnl = df["Netto G&V"].sum()
realized_pnl = realized_df["Netto G&V"].sum()
open_premium = open_df["Netto G&V"].sum()
reserved_cash = open_df["Kapitalbindung"].sum()

csp_pnl = df[df["Strategie"] == "CSP"]["Netto G&V"].sum()
cc_pnl = df[df["Strategie"] == "CC"]["Netto G&V"].sum()

win_rate = (len(realized_df[realized_df["Netto G&V"] > 0]) / len(realized_df) * 100) if len(realized_df) > 0 else 0.0

# Salden-Kacheln immer sichtbar ganz oben
m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("💰 Gesamt-Saldo (Netto)", f"{total_net_pnl:,.2f} $", f"Realisiert: {realized_pnl:,.2f} $")
m2.metric("⏳ Offene Prämien (Netto)", f"{open_premium:,.2f} $", f"{len(open_df)} offene Trades")
m3.metric("🔒 Gebundenes Cash (CSP)", f"{reserved_cash:,.2f} $", "Margin / Reserve")
m4.metric("📊 CSP vs. CC Saldo", f"CSP: {csp_pnl:,.0f} $", f"CC: {cc_pnl:,.0f} $", delta_color="off")
m5.metric("🎯 Gewinnquote (Geschl.)", f"{win_rate:.1f} %", f"{len(realized_df)} abgeschlossene Trades")

st.divider()

# ==========================================
# --- SIDEBAR: NEUEN TRADE ERFASSEN ---
# ==========================================
st.sidebar.header("➕ Neuen Trade eintragen")

with st.sidebar.form("new_trade_form", clear_on_submit=True):
    f_date = st.date_input("Eröffnungsdatum", value=date.today())
    f_ticker = st.text_input("Ticker-Symbol (z.B. AAPL, SAP.DE)", value="").upper().strip()
    f_strat = st.selectbox("Strategie", ["CSP", "CC"])
    f_cont = st.number_input("Anzahl Kontrakte", min_value=1, value=1, step=1)
    f_strike = st.number_input("Strike-Preis ($ / €)", min_value=0.5, value=100.0, step=0.5)
    f_exp = st.date_input("Verfallsdatum", value=date.today())
    f_prem = st.number_input("Erhaltene Prämie pro Aktie", min_value=0.01, value=1.50, step=0.05)
    f_fee = st.number_input("Gebühren gesamt ($ / €)", min_value=0.0, value=2.50, step=0.50)
    f_note = st.text_input("Notiz (optional)", value="")

    submitted = st.form_submit_button("✅ Trade speichern", type="primary", use_container_width=True)

    if submitted:
        if not f_ticker:
            st.sidebar.error("Bitte ein Ticker-Symbol eingeben!")
        else:
            next_id = int(df["ID"].max() + 1) if not df.empty else 1
            new_row = pd.DataFrame([{
                "ID": next_id,
                "Eröffnet am": f_date,
                "Ticker": f_ticker,
                "Strategie": f_strat,
                "Kontrakte": int(f_cont),
                "Strike": float(f_strike),
                "Verfall": f_exp,
                "Prämie/Aktie": float(f_prem),
                "Rückkauf/Aktie": 0.0,
                "Gebühren": float(f_fee),
                "Status": "Offen",
                "Netto G&V": 0.0,
                "Kapitalbindung": 0.0,
                "Notiz": f_note
            }])
            st.session_state.trades_df = recalculate_df(pd.concat([df, new_row], ignore_index=True))
            st.rerun()

# ==========================================
# --- SIDEBAR: BACKUP (CSV EXPORT / IMPORT) ---
# ==========================================
st.sidebar.divider()
st.sidebar.header("💾 Datensicherung (CSV)")

csv_buffer = st.session_state.trades_df.to_csv(index=False).encode("utf-8")
st.sidebar.download_button(
    label="⬇️ Tagebuch als CSV speichern",
    data=csv_buffer,
    file_name=f"stillhalter_tagebuch_{date.today()}.csv",
    mime="text/csv",
    use_container_width=True
)

uploaded_file = st.sidebar.file_uploader("⬆️ Gespeicherte CSV laden", type=["csv"])
if uploaded_file is not None:
    try:
        loaded_df = pd.read_csv(uploaded_file)
        loaded_df["Eröffnet am"] = pd.to_datetime(loaded_df["Eröffnet am"]).dt.date
        loaded_df["Verfall"] = pd.to_datetime(loaded_df["Verfall"]).dt.date
        st.session_state.trades_df = recalculate_df(loaded_df)
        st.sidebar.success("Tagebuch erfolgreich geladen!")
    except Exception as e:
        st.sidebar.error(f"Fehler beim Laden der Datei: {e}")

# ==========================================
# --- HAUPTBEREICH: TABELLE & FILTER ---
# ==========================================
col_f1, col_f2, col_f3 = st.columns([1.5, 1.5, 2])
with col_f1:
    filter_status = st.multiselect(
        "Status filtern:",
        options=["Offen", "Verfallen (Gewinn)", "Zurückgekauft", "Angedient (Assigned)", "Gerollt"],
        default=["Offen", "Verfallen (Gewinn)", "Zurückgekauft", "Angedient (Assigned)", "Gerollt"]
    )
with col_f2:
    filter_strat = st.multiselect("Strategie filtern:", options=["CSP", "CC"], default=["CSP", "CC"])
with col_f3:
    st.info("💡 **Tipp:** Klicke direkt in die Tabelle, um den **Status** zu ändern, einen **Rückkaufpreis** einzutragen oder Zeilen zu löschen.")

filtered_df = df[df["Status"].isin(filter_status) & df["Strategie"].isin(filter_strat)]

edited_df = st.data_editor(
    filtered_df,
    use_container_width=True,
    hide_index=True,
    num_rows="dynamic",
    height=480,
    column_config={
        "ID": st.column_config.NumberColumn("ID", disabled=True, width="small"),
        "Strategie": st.column_config.SelectboxColumn("Strategie", options=["CSP", "CC"], required=True),
        "Status": st.column_config.SelectboxColumn(
            "Status",
            options=["Offen", "Verfallen (Gewinn)", "Zurückgekauft", "Angedient (Assigned)", "Gerollt"],
            required=True
        ),
        "Strike": st.column_config.NumberColumn("Strike", format="%.2f"),
        "Prämie/Aktie": st.column_config.NumberColumn("Prämie/Aktie", format="%.2f"),
        "Rückkauf/Aktie": st.column_config.NumberColumn("Rückkauf/Aktie", format="%.2f"),
        "Gebühren": st.column_config.NumberColumn("Gebühren", format="%.2f"),
        "Netto G&V": st.column_config.NumberColumn("Netto G&V", format="%.2f $", disabled=True),
        "Kapitalbindung": st.column_config.NumberColumn("Cash-Reserve", format="%.0f $", disabled=True),
    }
)

# Änderungen aus dem Editor übernehmen & neu berechnen
if not edited_df.equals(filtered_df):
    # Ungefilterte Zeilen beibehalten und bearbeitete aktualisieren
    untouched_df = df[~df.index.isin(filtered_df.index)]
    combined_df = pd.concat([untouched_df, edited_df], ignore_index=True)
    # Falls neue leere Zeilen über "+" hinzugefügt wurden, Standardwerte setzen
    combined_df["ID"] = range(1, len(combined_df) + 1)
    combined_df["Kontrakte"] = combined_df["Kontrakte"].fillna(1)
    combined_df["Strike"] = combined_df["Strike"].fillna(0.0)
    combined_df["Prämie/Aktie"] = combined_df["Prämie/Aktie"].fillna(0.0)
    combined_df["Rückkauf/Aktie"] = combined_df["Rückkauf/Aktie"].fillna(0.0)
    combined_df["Gebühren"] = combined_df["Gebühren"].fillna(0.0)
    combined_df["Strategie"] = combined_df["Strategie"].fillna("CSP")
    combined_df["Status"] = combined_df["Status"].fillna("Offen")
    
    st.session_state.trades_df = recalculate_df(combined_df)
    st.rerun()
