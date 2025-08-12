
import math
import io
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Mortgage & Eligibility Analyzer", page_icon="🏠", layout="wide")

# ---------- Utility functions ----------
def pmt(rate_annual_pct, n_years, principal):
    r = (rate_annual_pct/100.0)/12.0
    n = int(n_years*12)
    if n == 0:
        return 0.0
    if r == 0:
        return principal / n
    return principal * (r * (1 + r)**n) / ((1 + r)**n - 1)

def currency(x): return f"${x:,.0f}"
def pct(x): return f"{x:.2f}%"

def va_funding_fee_pct(down_frac, first_use=True):
    # Simplified VA tiers (first-use / subsequent use)
    if not first_use:
        if down_frac < 0.05: return 0.036
        if down_frac < 0.10: return 0.0175
        return 0.015
    if down_frac < 0.05: return 0.0215
    if down_frac < 0.10: return 0.015
    return 0.0125

def temp_buydown_yearly_rates(base_rate, scheme):
    # scheme: "Permanent", "2-1", "3-2-1"
    if scheme == "2-1":
        return [base_rate-2.0, base_rate-1.0]
    if scheme == "3-2-1":
        return [base_rate-3.0, base_rate-2.0, base_rate-1.0]
    return []

def present_value_of_diffs(diffs, base_rate_pct, term_years):
    i = (base_rate_pct/100.0)/12.0
    pv = 0.0
    m = 0
    for months, diff in diffs:
        for _ in range(months):
            m += 1
            pv += (diff / ((1+i)**m)) if i>0 else diff
    return pv

# ---------- Sidebar: Assumptions ----------
with st.sidebar:
    st.header("Assumptions & Overlays")
    closing_cost_pct = st.number_input("Estimated Closing Costs (% of Price)", value=3.0, step=0.25, min_value=0.0) / 100
    tax_rate = st.number_input("Property Tax Rate (% of Price / year)", value=0.60, step=0.05, min_value=0.0) / 100
    ins_rate = st.number_input("Homeowners Insurance (% of Price / year)", value=0.35, step=0.05, min_value=0.0) / 100
    pmi_rate = st.number_input("PMI (Conventional) Annual Rate (% of balance)", value=0.60, step=0.10, min_value=0.0) / 100
    fha_ufmip_pct = st.number_input("FHA Upfront MIP (% of loan)", value=1.75, step=0.10, min_value=0.0) / 100
    fha_annual_mip = st.number_input("FHA Annual MIP (% of balance)", value=0.55, step=0.05, min_value=0.0) / 100

    st.divider()
    st.caption("Eligibility thresholds (edit to match your overlays)")
    min_credit_conv = st.number_input("Min Credit Conventional", value=620, step=10)
    min_credit_fha = st.number_input("Min Credit FHA", value=580, step=10)
    min_credit_va = st.number_input("Min Credit VA", value=580, step=10)
    max_dti_conv = st.number_input("Max DTI Conventional", value=45.0, step=1.0) / 100
    max_dti_fha  = st.number_input("Max DTI FHA", value=50.0, step=1.0) / 100
    max_dti_va   = st.number_input("Max DTI VA", value=55.0, step=1.0) / 100

    st.divider()
    st.caption("Pricing (simplified)")
    points_pct = st.number_input("Discount/Origination Points (% of loan)", value=0.00, step=0.125, min_value=0.0) / 100
    rate_reduction_per_point = st.number_input("Rate Reduction per 1.0 Point (bps)", value=25, step=5, min_value=0) / 100  # 25 bps = 0.25%
    apply_points_to_builder_rate = st.checkbox("Apply points to Builder rate", value=False)

# ---------- Main Inputs ----------
st.title("🏠 Mortgage & Eligibility Analyzer")
st.caption("Compare builder vs outside lender, apply incentives (price reduction, closing credit, rate buydown), and evaluate program eligibility.")

colA, colB, colC = st.columns(3)
with colA:
    price = st.number_input("Home Price ($)", value=550000, step=1000, min_value=0)
    down_payment = st.number_input("Down Payment ($)", value=30000, step=1000, min_value=0)
    hoa = st.number_input("HOA Dues ($/mo)", value=0, step=10, min_value=0)
    occ = st.selectbox("Occupancy", ["Primary","Second Home","Investment"])
with colB:
    credit_score = st.number_input("Credit Score", value=700, step=1, min_value=300, max_value=900)
    gross_monthly_income = st.number_input("Gross Monthly Income ($)", value=11000, step=100, min_value=0)
    existing_monthly_debts = st.number_input("Existing Monthly Debts ($)", value=1200, step=50, min_value=0)
with colC:
    loan_term = st.number_input("Loan Term (years)", value=30, step=5, min_value=5, max_value=40)
    rate_builder = st.number_input("Builder Lender Rate (%)", value=6.75, step=0.125, min_value=0.0)
    rate_outside = st.number_input("Outside Lender Rate (%)", value=7.00, step=0.125, min_value=0.0)

elig_cols = st.columns(5)
with elig_cols[0]:
    va_eligible = st.selectbox("VA Eligible?", ["No","Yes"])
with elig_cols[1]:
    va_first_use = st.selectbox("VA First Use?", ["Yes","No"])
with elig_cols[2]:
    usda_eligible = st.selectbox("USDA Eligible? (basic flag)", ["No","Yes"])
with elig_cols[3]:
    recent_bk = st.selectbox("Bankruptcy in last 4 yrs?", ["No","Yes"])
with elig_cols[4]:
    recent_fc = st.selectbox("Foreclosure in last 7 yrs?", ["No","Yes"])

st.divider()

# ---------- Incentive Controls ----------
st.subheader("Builder Incentive")
inc_type = st.selectbox("Incentive Type", ["ClosingCredit", "PriceReduction", "RateBuydown"])
inc_amount = st.number_input("Incentive Amount ($)", value=10000, step=1000, min_value=0)

# Rate buydown flavor
buydown_scheme = "Permanent"
if inc_type == "RateBuydown":
    buydown_scheme = st.selectbox("Buydown Scheme", ["Permanent", "2-1", "3-2-1"])
    if buydown_scheme == "Permanent":
        st.info("Enter the **reduced builder rate** after buydown.")
        rate_builder = st.number_input("Builder Lender Rate After Permanent Buydown (%)", value=6.25, step=0.125, min_value=0.0)

# Apply points to rate (optional)
if apply_points_to_builder_rate and points_pct > 0:
    rate_builder = max(0.0, rate_builder - (rate_reduction_per_point * (points_pct*100)))  # fraction -> points

# Adjusted price when price reduction is selected
adj_price = price - inc_amount if inc_type == "PriceReduction" else price

# ---------- Scenarios ----------
st.subheader("Scenarios")
default_scenarios = [
    {"name": "Scenario 1 (Builder Lender)", "rate": rate_builder, "use_incentive": True},
    {"name": "Scenario 2 (Outside Lender)", "rate": rate_outside, "use_incentive": False},
    {"name": "Scenario 3 (Custom)", "rate": rate_builder, "use_incentive": True},
]

scenario_data = []
for i, base in enumerate(default_scenarios, start=1):
    with st.expander(base["name"], expanded=(i==1)):
        scen_name = st.text_input("Scenario Name", value=base["name"], key=f"name_{i}")
        scen_rate = st.number_input("Note Rate (%)", value=float(base["rate"]), step=0.125, key=f"rate_{i}")
        scen_use_inc = st.selectbox("Use Builder Incentive?", ["Yes","No"], index=0 if base["use_incentive"] else 1, key=f"useinc_{i}")
        scen_down = st.number_input("Down Payment ($)", value=down_payment, step=1000, min_value=0, key=f"down_{i}")

        scen_price = adj_price if (inc_type=="PriceReduction" and scen_use_inc=="Yes") else price
        closing_credit = inc_amount if (inc_type=="ClosingCredit" and scen_use_inc=="Yes") else 0

        base_loan = max(0.0, scen_price - scen_down)

        # Program hint
        prog_hint = "VA" if va_eligible=="Yes" else ("FHA" if credit_score < min_credit_conv else "Conventional")

        # Finance FHA UFMIP or VA funding fee
        fhava_note = ""
        loan_amount = base_loan
        upfront_costs_financed = 0.0
        if prog_hint == "FHA":
            ufmip = base_loan * fha_ufmip_pct
            loan_amount = base_loan + ufmip
            upfront_costs_financed = ufmip
            fhava_note = f"FHA UFMIP financed: {currency(ufmip)}"
        elif prog_hint == "VA":
            down_frac = scen_down / scen_price if scen_price else 0.0
            fee_pct = va_funding_fee_pct(down_frac, first_use=(va_first_use=="Yes"))
            va_fee = base_loan * fee_pct
            loan_amount = base_loan + va_fee
            upfront_costs_financed = va_fee
            fhava_note = f"VA Funding Fee ({pct(fee_pct*100)} of base loan) financed: {currency(va_fee)}"

        monthly_tax = scen_price * tax_rate / 12.0
        monthly_ins = scen_price * ins_rate / 12.0

        ltv = loan_amount / scen_price if scen_price else 0.0
        if prog_hint == "Conventional" and ltv > 0.80:
            pmi_mip = loan_amount * pmi_rate / 12.0
        elif prog_hint == "FHA":
            pmi_mip = loan_amount * fha_annual_mip / 12.0
        else:
            pmi_mip = 0.0

        monthly_pi = pmt(scen_rate, loan_term, loan_amount)

        buydown_details = {}
        if inc_type == "RateBuydown" and scen_use_inc == "Yes" and i == 1:
            if buydown_scheme in ["2-1", "3-2-1"]:
                yr_rates = []
                if buydown_scheme == "2-1":
                    yr_rates = [scen_rate-2.0, scen_rate-1.0]
                elif buydown_scheme == "3-2-1":
                    yr_rates = [scen_rate-3.0, scen_rate-2.0, scen_rate-1.0]
                payments = []
                diffs = []
                for idx, r in enumerate(yr_rates, start=1):
                    pay = pmt(r, loan_term, loan_amount)
                    payments.append((idx, r, pay))
                    diffs.append((12, monthly_pi - pay))
                buydown_cost_pv = present_value_of_diffs(diffs, scen_rate, loan_term)
                buydown_cost_naive = sum(12*diff for _, diff in diffs)
                buydown_details = {"scheme": buydown_scheme, "yearly_payments": payments, "pv_cost": buydown_cost_pv, "sum_cost": buydown_cost_naive}

        piti = monthly_pi + monthly_tax + monthly_ins + pmi_mip + hoa
        dti = (existing_monthly_debts + piti) / gross_monthly_income if gross_monthly_income else 0.0

        conv_ok = (credit_score >= min_credit_conv) and (dti <= max_dti_conv) and (recent_bk=="No") and (recent_fc=="No")
        fha_ok  = (credit_score >= min_credit_fha) and (dti <= max_dti_fha)
        va_ok   = (va_eligible=="Yes") and (credit_score >= min_credit_va) and (dti <= max_dti_va) and (occ=="Primary")

        est_closing_costs = scen_price * closing_cost_pct + (points_pct * base_loan)
        cash_to_close = scen_down + max(0.0, est_closing_costs - closing_credit)

        warning_msgs = []
        if occ != "Primary" and prog_hint in ["FHA","VA","USDA"]:
            warning_msgs.append("Government programs generally require **primary occupancy**.")
        if prog_hint == "Conventional" and ltv > 0.95:
            warning_msgs.append("High LTV Conventional may require special programs or pricing.")
        if prog_hint == "FHA" and ltv > 0.965:
            warning_msgs.append("FHA max LTV/loan limits may apply—verify guidelines for your county.")
        if prog_hint == "VA" and va_eligible == "No":
            warning_msgs.append("VA selected but borrower not flagged as VA-eligible.")
        if inc_type == "RateBuydown" and scen_use_inc=="Yes" and buydown_details:
            if inc_amount < buydown_details["pv_cost"]:
                warning_msgs.append("Incentive may be insufficient to fully fund the temporary buydown (PV of subsidy exceeds incentive).")

        scenario_data.append(dict(
            name=scen_name,
            price=scen_price,
            note_rate=scen_rate,
            down=scen_down,
            loan_amount=loan_amount,
            base_loan=base_loan,
            financed_upfront=upfront_costs_financed,
            monthly_pi=monthly_pi,
            monthly_tax=monthly_tax,
            monthly_ins=monthly_ins,
            hoa=hoa,
            pmi_mip=pmi_mip,
            piti=piti,
            dti=dti,
            closing_credit=closing_credit,
            est_closing_costs=est_closing_costs,
            cash_to_close=cash_to_close,
            program_hint=prog_hint,
            conv_ok=conv_ok,
            fha_ok=fha_ok,
            va_ok=va_ok,
            fhava_note=fhava_note,
            buydown_details=buydown_details,
            warnings=warning_msgs
        ))

# ---------- Summary ----------
df = pd.DataFrame([{
    "Scenario": s["name"],
    "Price": s["price"],
    "Rate %": s["note_rate"],
    "Down $": s["down"],
    "Loan $": s["loan_amount"],
    "Financed Upfront $": s["financed_upfront"],
    "P&I $/mo": s["monthly_pi"],
    "Tax $/mo": s["monthly_tax"],
    "Ins $/mo": s["monthly_ins"],
    "PMI/MIP $/mo": s["pmi_mip"],
    "HOA $/mo": s["hoa"],
    "PITI $/mo": s["piti"],
    "DTI": s["dti"],
    "Est Closing Costs $": s["est_closing_costs"],
    "Builder Closing Credit $": s["closing_credit"],
    "Cash to Close $": s["cash_to_close"],
    "Program Hint": s["program_hint"],
    "Conv OK": s["conv_ok"],
    "FHA OK": s["fha_ok"],
    "VA OK": s["va_ok"],
} for s in scenario_data])

st.subheader("Summary")
st.dataframe(df.style.format({
    "Price": "${:,.0f}",
    "Rate %": "{:.3f}",
    "Down $": "${:,.0f}",
    "Loan $": "${:,.0f}",
    "Financed Upfront $": "${:,.0f}",
    "P&I $/mo": "${:,.0f}",
    "Tax $/mo": "${:,.0f}",
    "Ins $/mo": "${:,.0f}",
    "PMI/MIP $/mo": "${:,.0f}",
    "HOA $/mo": "${:,.0f}",
    "PITI $/mo": "${:,.0f}",
    "DTI": "{:.1%}",
    "Est Closing Costs $": "${:,.0f}",
    "Builder Closing Credit $": "${:,.0f}",
    "Cash to Close $": "${:,.0f}",
}))

# ---------- Baseline comparison ----------
st.divider()
st.subheader("Builder vs Outside Lender (P&I Only, baseline)")
adj_base = adj_price if inc_type == "PriceReduction" else price
loan_amount_base = max(0.0, adj_base - down_payment)
rate_builder_baseline = rate_builder
if apply_points_to_builder_rate and points_pct > 0:
    rate_builder_baseline = max(0.0, rate_builder_baseline - (rate_reduction_per_point * (points_pct*100)))
pi_builder = pmt(rate_builder_baseline, loan_term, loan_amount_base)
pi_outside = pmt(rate_outside, loan_term, loan_amount_base)

c1, c2, c3 = st.columns(3)
with c1: st.metric("Builder P&I / mo", currency(pi_builder))
with c2: st.metric("Outside Lender P&I / mo", currency(pi_outside))
with c3: st.metric("Monthly Difference", currency(pi_outside - pi_builder))

# ---------- Details & Warnings ----------
builder_scen = next((s for s in scenario_data if "Builder" in s["name"]), None)
if builder_scen:
    st.subheader("Builder Scenario Details")
    st.write(f"**Program Hint:** {builder_scen['program_hint']}")
    if builder_scen["fhava_note"]:
        st.write(builder_scen["fhava_note"])
    if builder_scen["buydown_details"]:
        bd = builder_scen["buydown_details"]
        st.write(f"**Temporary Buydown:** {bd['scheme']}")
        for (yr, rate, pay) in bd["yearly_payments"]:
            st.write(f"Year {yr}: Rate {rate:.3f}% → P&I {currency(pay)}")
        st.write(f"PV of Subsidy Cost: {currency(bd['pv_cost'])} (sum of diffs: {currency(bd['sum_cost'])})")
    if builder_scen["warnings"]:
        for w in builder_scen["warnings"]:
            st.warning(w)

# ---------- Downloadable Report ----------
st.divider()
st.subheader("Download Report")
scenario_names = [s["name"] for s in scenario_data]
if scenario_names:
    selected = st.selectbox("Select Scenario for Report", options=scenario_names, index=0)
    sel = next(s for s in scenario_data if s["name"] == selected)
    report_html = f"""
    <html>
    <head><meta charset='utf-8'><title>Mortgage Report</title></head>
    <body>
    <h2>Mortgage Scenario Report – {sel['name']}</h2>
    <p><strong>Program Hint:</strong> {sel['program_hint']}</p>
    <ul>
      <li>Price: {currency(sel['price'])}</li>
      <li>Down: {currency(sel['down'])}</li>
      <li>Note Rate: {sel['note_rate']:.3f}%</li>
      <li>Loan Amount (after financed fees if any): {currency(sel['loan_amount'])}</li>
      <li>Financed Upfront: {currency(sel['financed_upfront'])}</li>
      <li>P&I / mo: {currency(sel['monthly_pi'])}</li>
      <li>Taxes / mo: {currency(sel['monthly_tax'])}</li>
      <li>Insurance / mo: {currency(sel['monthly_ins'])}</li>
      <li>PMI/MIP / mo: {currency(sel['pmi_mip'])}</li>
      <li>HOA / mo: {currency(sel['hoa'])}</li>
      <li><strong>PITI / mo: {currency(sel['piti'])}</strong></li>
      <li><strong>DTI:</strong> {sel['dti']*100:.1f}%</li>
      <li>Est. Closing Costs: {currency(sel['est_closing_costs'])}</li>
      <li>Builder Closing Credit: {currency(sel['closing_credit'])}</li>
      <li><strong>Cash to Close: {currency(sel['cash_to_close'])}</strong></li>
    </ul>
    <p>{sel['fhava_note']}</p>
    """
    if sel["buydown_details"]:
        bd = sel["buydown_details"]
        rows = "".join([f"<li>Year {yr}: {rate:.3f}% → P&I {currency(pay)}</li>" for (yr, rate, pay) in bd["yearly_payments"]])
        report_html += f"""
        <h3>Temporary Buydown</h3>
        <ul>{rows}</ul>
        <p>PV of Subsidy Cost: {currency(bd['pv_cost'])} (sum of diffs: {currency(bd['sum_cost'])})</p>
        """
    if sel["warnings"]:
        warns = "".join([f"<li>{w}</li>" for w in sel["warnings"]])
        report_html += f"<h3>Notes & Warnings</h3><ul>{warns}</ul>"
    report_html += "<p style='font-size:12px;color:#666'>Estimates only. Not a commitment to lend. Verify program rules, loan limits, and overlays.</p></body></html>"

    st.download_button("Download HTML Report", data=report_html.encode("utf-8"), file_name="mortgage_report.html", mime="text/html")

st.caption("This tool is for estimates only and not a loan offer. Customize assumptions to match your guidelines and pricing.")
