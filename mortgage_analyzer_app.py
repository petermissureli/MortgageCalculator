# mortgage_analyzer_app.py
# Streamlit Mortgage Analyzer with 4 scenarios, charts, and PDF export
# - 3 internal options with lender credits
# - 1 external lender option
# - Comparison charts + per-scenario payoff charts
# - One-click multipage PDF export
#
# Run: streamlit run mortgage_analyzer_app.py

from __future__ import annotations
import io
from dataclasses import dataclass
from typing import Dict, List

import numpy as np
import pandas as pd
import streamlit as st
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages

st.set_page_config(page_title="Mortgage Analyzer", layout="wide")

# ---------- Core math ----------

@dataclass
class MortgageInputs:
    name: str
    home_price: float
    down_payment: float
    annual_rate_pct: float
    term_years: int
    property_tax_annual: float = 0.0
    insurance_annual: float = 0.0
    hoa_monthly: float = 0.0
    lender_credit_pct: float = 0.0   # % of loan amount credited to closing costs (negative means points)
    est_closing_costs_pct: float = 0.03
    extra_principal_monthly: float = 0.0

def monthly_payment(principal: float, annual_rate_pct: float, term_years: int) -> float:
    r = (annual_rate_pct / 100.0) / 12.0
    n = term_years * 12
    if r == 0:
        return principal / n
    return principal * (r * (1 + r) ** n) / ((1 + r) ** n - 1)

def build_amortization(inputs: MortgageInputs) -> pd.DataFrame:
    loan_amount = inputs.home_price - inputs.down_payment
    r = (inputs.annual_rate_pct / 100.0) / 12.0
    n = inputs.term_years * 12

    base_pmt = monthly_payment(loan_amount, inputs.annual_rate_pct, inputs.term_years)
    tax_m = inputs.property_tax_annual / 12.0
    ins_m = inputs.insurance_annual / 12.0
    hoa_m = inputs.hoa_monthly

    bal = loan_amount
    rows = []
    for m in range(1, n + 1):
        interest = bal * r
        principal = base_pmt - interest + inputs.extra_principal_monthly
        if principal > bal:
            principal = bal
        bal -= principal
        rows.append({
            "Month": m,
            "Payment_PnI": base_pmt + inputs.extra_principal_monthly,
            "Interest": interest,
            "Principal": principal,
            "Escrow_Tax": tax_m,
            "Escrow_Ins": ins_m,
            "HOA": hoa_m,
            "Total_Outlay": (base_pmt + inputs.extra_principal_monthly) + tax_m + ins_m + hoa_m,
            "Balance": bal
        })
        if bal <= 1e-6:
            break

    df = pd.DataFrame(rows)

    upfront_base = loan_amount * inputs.est_closing_costs_pct
    lender_credit = loan_amount * inputs.lender_credit_pct
    upfront_net = max(upfront_base - lender_credit, 0.0)

    df.attrs["loan_amount"] = loan_amount
    df.attrs["base_pmt"] = base_pmt
    df.attrs["total_interest"] = float(df["Interest"].sum())
    df.attrs["months_to_payoff"] = len(df)
    df.attrs["upfront_base"] = upfront_base
    df.attrs["lender_credit"] = lender_credit
    df.attrs["upfront_net"] = upfront_net
    df.attrs["total_outlay_all_in"] = float(df["Total_Outlay"].sum() + upfront_net)
    return df

# ---------- UI: Sidebar inputs ----------

st.title("Mortgage Analyzer — 4-Scenario Comparison")

with st.sidebar:
    st.header("Assumptions")
    home_price = st.number_input("Home price", value=550_000.0, min_value=10_000.0, step=1000.0, format="%.2f")
    down_payment = st.number_input("Down payment", value=110_000.0, min_value=0.0, step=1000.0, format="%.2f")
    term_years = st.number_input("Term (years)", value=30, min_value=5, max_value=40, step=5)
    property_tax_annual = st.number_input("Property tax (annual)", value=5_000.0, min_value=0.0, step=100.0, format="%.2f")
    insurance_annual = st.number_input("Homeowners insurance (annual)", value=1_800.0, min_value=0.0, step=50.0, format="%.2f")
    hoa_monthly = st.number_input("HOA (monthly)", value=60.0, min_value=0.0, step=5.0, format="%.2f")
    extra_principal_monthly = st.number_input("Extra principal (monthly)", value=0.0, min_value=0.0, step=25.0, format="%.2f")
    est_closing_costs_pct = st.number_input("Baseline closing costs (% of loan)", value=3.0, min_value=0.0, max_value=10.0, step=0.1) / 100.0

    st.markdown("---")
    st.subheader("Scenario Rates & Credits")
    colA, colB = st.columns(2)
    with colA:
        rate_int_A = st.number_input("Internal A rate (%)", value=5.875, step=0.01, format="%.3f")
        rate_int_B = st.number_input("Internal B rate (%)", value=6.000, step=0.01, format="%.3f")
    with colB:
        rate_int_C = st.number_input("Internal C rate (%)", value=6.125, step=0.01, format="%.3f")
        rate_ext   = st.number_input("External rate (%)",   value=5.750, step=0.01, format="%.3f")

    colC, colD = st.columns(2)
    with colC:
        credit_A_pct = st.number_input("Internal A lender credit (%)", value=1.0, step=0.25, format="%.2f")/100.0
        credit_B_pct = st.number_input("Internal B lender credit (%)", value=1.5, step=0.25, format="%.2f")/100.0
    with colD:
        credit_C_pct = st.number_input("Internal C lender credit (%)", value=2.0, step=0.25, format="%.2f")/100.0
        credit_ext_pct = st.number_input("External lender credit (%)", value=0.0, step=0.25, format="%.2f")/100.0

# ---------- Build scenarios ----------

def make_scenarios() -> List[MortgageInputs]:
    base = dict(
        home_price=home_price,
        down_payment=down_payment,
        term_years=term_years,
        property_tax_annual=property_tax_annual,
        insurance_annual=insurance_annual,
        hoa_monthly=hoa_monthly,
        extra_principal_monthly=extra_principal_monthly,
        est_closing_costs_pct=est_closing_costs_pct,
    )
    return [
        MortgageInputs(name="Internal A (Credit 1%)", annual_rate_pct=rate_int_A, lender_credit_pct=credit_A_pct, **base),
        MortgageInputs(name="Internal B (Credit 1.5%)", annual_rate_pct=rate_int_B, lender_credit_pct=credit_B_pct, **base),
        MortgageInputs(name="Internal C (Credit 2%)", annual_rate_pct=rate_int_C, lender_credit_pct=credit_C_pct, **base),
        MortgageInputs(name="External (No / Custom Credit)", annual_rate_pct=rate_ext, lender_credit_pct=credit_ext_pct, **base),
    ]

scenarios = make_scenarios()

# ---------- Compute & summarize ----------

schedules: Dict[str, pd.DataFrame] = {}
summary_rows: List[Dict[str, float]] = []

for sc in scenarios:
    df = build_amortization(sc)
    schedules[sc.name] = df
    summary_rows.append({
        "Scenario": sc.name,
        "Rate_%": sc.annual_rate_pct,
        "Loan_Amount": df.attrs["loan_amount"],
        "Monthly_P&I": round(df.attrs["base_pmt"], 2),
        "Escrow+HOA": round((sc.property_tax_annual/12.0) + (sc.insurance_annual/12.0) + sc.hoa_monthly, 2),
        "Months_to_Payoff": df.attrs["months_to_payoff"],
        "Total_Interest": round(df.attrs["total_interest"], 2),
        "Upfront_Base": round(df.attrs["upfront_base"], 2),
        "Lender_Credit": round(df.attrs["lender_credit"], 2),
        "Upfront_Net": round(df.attrs["upfront_net"], 2),
        "Total_All_In_Outlay": round(df.attrs["total_outlay_all_in"], 2),
    })

summary_df = pd.DataFrame(summary_rows)

st.subheader("Scenario Summary")
st.dataframe(
    summary_df.style.format({
        "Rate_%": "{:.3f}",
        "Loan_Amount": "${:,.0f}",
        "Monthly_P&I": "${:,.2f}",
        "Escrow+HOA": "${:,.2f}",
        "Total_Interest": "${:,.0f}",
        "Upfront_Base": "${:,.0f}",
        "Lender_Credit": "${:,.0f}",
        "Upfront_Net": "${:,.0f}",
        "Total_All_In_Outlay": "${:,.0f}",
    }),
    use_container_width=True,
)

# ---------- Charts (Matplotlib) ----------

def fig_monthly_pi_bar() -> plt.Figure:
    labels = summary_df["Scenario"].tolist()
    vals = summary_df["Monthly_P&I"].values
    x = np.arange(len(labels))
    fig = plt.figure(figsize=(9, 4))
    plt.bar(x, vals)
    plt.xticks(x, labels, rotation=15, ha="right")
    plt.ylabel("Monthly P&I ($)")
    plt.title("Monthly Principal & Interest by Scenario")
    for i, v in enumerate(vals):
        plt.text(i, v, f"{v:,.0f}", ha="center", va="bottom", fontsize=8)
    fig.tight_layout()
    return fig

def fig_upfront_net_bar() -> plt.Figure:
    labels = summary_df["Scenario"].tolist()
    vals = summary_df["Upfront_Net"].values
    x = np.arange(len(labels))
    fig = plt.figure(figsize=(9, 4))
    plt.bar(x, vals)
    plt.xticks(x, labels, rotation=15, ha="right")
    plt.ylabel("Net Upfront ($)")
    plt.title("Net Upfront Costs (after Lender Credits)")
    for i, v in enumerate(vals):
        plt.text(i, v, f"{v:,.0f}", ha="center", va="bottom", fontsize=8)
    fig.tight_layout()
    return fig

def fig_total_interest_bar() -> plt.Figure:
    labels = summary_df["Scenario"].tolist()
    vals = summary_df["Total_Interest"].values
    x = np.arange(len(labels))
    fig = plt.figure(figsize=(9, 4))
    plt.bar(x, vals)
    plt.xticks(x, labels, rotation=15, ha="right")
    plt.ylabel("Total Interest ($)")
    plt.title("Total Interest over Life of Loan")
    for i, v in enumerate(vals):
        plt.text(i, v, f"{v:,.0f}", ha="center", va="bottom", fontsize=8)
    fig.tight_layout()
    return fig

def fig_payoff_lines(name: str, df: pd.DataFrame) -> plt.Figure:
    fig = plt.figure(figsize=(9, 4))
    plt.plot(df["Month"], df["Interest"], label="Interest Portion")
    plt.plot(df["Month"], df["Principal"], label="Principal Portion")
    plt.xlabel("Month")
    plt.ylabel("Dollars")
    plt.title(f"{name}: Monthly P&I Breakdown")
    plt.legend()
    fig.tight_layout()
    return fig

def fig_cum_lines(name: str, df: pd.DataFrame) -> plt.Figure:
    fig = plt.figure(figsize=(9, 4))
    plt.plot(df["Month"], df["Principal"].cumsum(), label="Cumulative Principal")
    plt.plot(df["Month"], df["Interest"].cumsum(), label="Cumulative Interest")
    plt.xlabel("Month")
    plt.ylabel("Dollars")
    plt.title(f"{name}: Cumulative Principal vs Interest")
    plt.legend()
    fig.tight_layout()
    return fig

c1, c2 = st.columns(2)
with c1:
    st.pyplot(fig_monthly_pi_bar(), use_container_width=True)
with c2:
    st.pyplot(fig_upfront_net_bar(), use_container_width=True)

st.pyplot(fig_total_interest_bar(), use_container_width=True)

st.markdown("### Per-Scenario Payoff Views")
for sc in scenarios:
    df = schedules[sc.name]
    pc1, pc2 = st.columns(2)
    with pc1:
        st.pyplot(fig_payoff_lines(sc.name, df), use_container_width=True)
    with pc2:
        st.pyplot(fig_cum_lines(sc.name, df), use_container_width=True)
    # Offer CSV for this scenario
    csv = df.to_csv(index=False).encode("utf-8")
    st.download_button(
        label=f"Download amortization CSV — {sc.name}",
        data=csv,
        file_name=f"{sc.name.replace(' ', '_').replace('(', '').replace(')', '')}_Amortization.csv",
        mime="text/csv",
        key=f"csv_{sc.name}",
    )
    st.markdown("---")

# ---------- PDF export (multi-page) ----------

def build_pdf() -> bytes:
    buf = io.BytesIO()
    with PdfPages(buf) as pp:
        # Cover
        fig = plt.figure(figsize=(8.5, 11))
        plt.axis("off")
        plt.text(0.5, 0.92, "Mortgage Scenarios Report", ha="center", va="center", fontsize=22, weight="bold")
        plt.text(0.5, 0.885, "3 Internal Options (with lender credits) + 1 External Lender", ha="center", va="center", fontsize=11)
        assumptions = [
            f"Home price: ${home_price:,.0f}",
            f"Down payment: ${down_payment:,.0f}",
            f"Term: {term_years} years",
            f"Property tax (annual): ${property_tax_annual:,.0f}",
            f"Insurance (annual): ${insurance_annual:,.0f}",
            f"HOA (monthly): ${hoa_monthly:,.0f}",
            f"Baseline closing costs: {est_closing_costs_pct*100:.2f}% of loan",
            f"Extra principal (monthly): ${extra_principal_monthly:,.0f}",
        ]
        y = 0.82
        for line in assumptions:
            plt.text(0.08, y, f"• {line}", fontsize=10, va="top")
            y -= 0.04
        pp.savefig(fig); plt.close(fig)

        # Comparison charts
        for make_fig in (fig_monthly_pi_bar, fig_upfront_net_bar, fig_total_interest_bar):
            fig = make_fig()
            fig.set_size_inches(11, 8.5)
            pp.savefig(fig); plt.close(fig)

        # Summary table as text
        fig = plt.figure(figsize=(11, 8.5))
        plt.axis("off")
        plt.title("Scenario Summary", loc="left", fontsize=14, pad=12)
        y = 0.88
        for _, row in summary_df.iterrows():
            line = (
                f"{row['Scenario']}:  Rate {row['Rate_%']:.3f}%,  P&I ${row['Monthly_P&I']:,.2f},  "
                f"Upfront Net ${row['Upfront_Net']:,.0f},  Total Interest ${row['Total_Interest']:,.0f},  "
                f"All-in ${row['Total_All_In_Outlay']:,.0f}"
            )
            plt.text(0.03, y, line, fontsize=10, va="top")
            y -= 0.05
        pp.savefig(fig); plt.close(fig)

        # Per-scenario pages
        for sc in scenarios:
            df = schedules[sc.name]
            for maker in (fig_payoff_lines, fig_cum_lines):
                fig = maker(sc.name, df)
                fig.set_size_inches(11, 8.5)
                pp.savefig(fig); plt.close(fig)
    return buf.getvalue()

st.markdown("### Export")
pdf_bytes = build_pdf()
st.download_button(
    label="📄 Download PDF report",
    data=pdf_bytes,
    file_name="Mortgage_Scenarios_Report.pdf",
    mime="application/pdf",
)
