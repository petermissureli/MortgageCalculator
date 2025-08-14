
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Mortgage & Eligibility Analyzer (Basic)", page_icon="🏠", layout="wide")

def pmt(rate_annual_pct, n_years, principal):
    r = (rate_annual_pct/100.0)/12.0
    n = int(n_years*12)
    if r == 0:
        return principal / n if n else 0.0
    return principal * (r * (1 + r)**n) / ((1 + r)**n - 1)

def currency(x): return f"${x:,.0f}"

# Sidebar assumptions
with st.sidebar:
    st.header("Assumptions")
    closing_cost_pct = st.number_input("Estimated Closing Costs (% of Price)", value=3.0, step=0.25, min_value=0.0) / 100
    tax_rate = st.number_input("Property Tax Rate (% of Price / year)", value=0.60, step=0.05, min_value=0.0) / 100
    ins_rate = st.number_input("Homeowners Insurance Rate (% of Price / year)", value=0.35, step=0.05, min_value=0.0) / 100
    pmi_rate = st.number_input("PMI (Conventional) Annual Rate (% of balance)", value=0.60, step=0.10, min_value=0.0) / 100
    min_credit_conv = st.number_input("Min Credit Conventional", value=620, step=10)
    min_credit_fha = st.number_input("Min Credit FHA", value=580, step=10)
    min_credit_va = st.number_input("Min Credit VA", value=580, step=10)
    max_dti_conv = st.number_input("Max DTI Conventional", value=45.0, step=1.0) / 100
    max_dti_fha  = st.number_input("Max DTI FHA", value=50.0, step=1.0) / 100
    max_dti_va   = st.number_input("Max DTI VA", value=55.0, step=1.0) / 100

st.title("🏠 Mortgage & Eligibility Analyzer — Basic")

colA, colB, colC = st.columns(3)
with colA:
    price = st.number_input("Home Price ($)", value=550000, step=1000, min_value=0)
    down_payment = st.number_input("Down Payment ($)", value=30000, step=1000, min_value=0)
    hoa = st.number_input("HOA Dues ($/mo)", value=0, step=10, min_value=0)
with colB:
    credit_score = st.number_input("Credit Score", value=700, step=1, min_value=300, max_value=900)
    gross_monthly_income = st.number_input("Gross Monthly Income ($)", value=11000, step=100, min_value=0)
    existing_monthly_debts = st.number_input("Existing Monthly Debts ($)", value=1200, step=50, min_value=0)
with colC:
    loan_term = st.number_input("Loan Term (years)", value=30, step=5, min_value=5, max_value=40)
    rate_builder = st.number_input("Builder Lender Rate (%)", value=6.75, step=0.125, min_value=0.0)
    rate_outside = st.number_input("Outside Lender Rate (%)", value=7.00, step=0.125, min_value=0.0)

elig_cols = st.columns(4)
with elig_cols[0]:
    va_eligible = st.selectbox("VA Eligible?", ["No","Yes"])
with elig_cols[1]:
    st.selectbox("USDA Eligible? (not modeled)", ["No","Yes"])
with elig_cols[2]:
    recent_bk = st.selectbox("Bankruptcy in last 4 yrs?", ["No","Yes"])
with elig_cols[3]:
    recent_fc = st.selectbox("Foreclosure in last 7 yrs?", ["No","Yes"])

st.markdown("---")
st.subheader("Builder Incentive")
inc_type = st.selectbox("Incentive Type", ["ClosingCredit", "PriceReduction", "RateBuydown"])
inc_amount = st.number_input("Incentive Amount ($)", value=10000, step=1000, min_value=0)
if inc_type == "RateBuydown":
    st.info("Enter the **reduced builder rate** after buydown.")
    rate_builder = st.number_input("Builder Lender Rate After Buydown (%)", value=6.25, step=0.125, min_value=0.0)
adj_price = price - inc_amount if inc_type == "PriceReduction" else price

# Scenarios (3 generic + builder vs outside comparison)
st.subheader("Scenarios")
default_scenarios = [
    {"name": "Scenario 1 (Builder Lender)", "rate": rate_builder, "use_incentive": True},
    {"name": "Scenario 2 (Outside Lender)", "rate": rate_outside, "use_incentive": False},
    {"name": "Scenario 3 (Custom)", "rate": rate_builder, "use_incentive": True},
]

rows = []
for i, base in enumerate(default_scenarios, start=1):
    with st.expander(base["name"], expanded=(i==1)):
        scen_name = st.text_input("Scenario Name", value=base["name"], key=f"name_{i}")
        scen_rate = st.number_input("Interest Rate (%)", value=float(base["rate"]), step=0.125, key=f"rate_{i}")
        scen_use_inc = st.selectbox("Use Builder Incentive?", ["Yes","No"], index=0 if base["use_incentive"] else 1, key=f"useinc_{i}")
        scen_down = st.number_input("Down Payment ($)", value=down_payment, step=1000, min_value=0, key=f"down_{i}")
        scen_price = adj_price if (inc_type=="PriceReduction" and scen_use_inc=="Yes") else price
        closing_credit = inc_amount if (inc_type=="ClosingCredit" and scen_use_inc=="Yes") else 0
        loan_amount = max(0.0, scen_price - scen_down)
        monthly_pi = pmt(scen_rate, loan_term, loan_amount)
        monthly_tax = scen_price * tax_rate / 12.0
        monthly_ins = scen_price * ins_rate / 12.0
        ltv = loan_amount / scen_price if scen_price else 0.0
        # Simple program hint and MI
        prog_hint = "VA" if va_eligible=="Yes" else ("FHA" if credit_score < min_credit_conv else "Conventional")
        pmi_mip = loan_amount * pmi_rate / 12.0 if (prog_hint=="Conventional" and ltv>0.8) else (loan_amount * 0.0055 / 12.0 if prog_hint=="FHA" else 0.0)
        piti = monthly_pi + monthly_tax + monthly_ins + hoa + pmi_mip
        dti = (existing_monthly_debts + piti) / gross_monthly_income if gross_monthly_income else 0.0
        est_closing_costs = scen_price * closing_cost_pct
        cash_to_close = scen_down + max(0.0, est_closing_costs - closing_credit)
        rows.append({
            "Scenario": scen_name, "Price": scen_price, "Rate %": scen_rate, "Down $": scen_down, "Loan $": loan_amount,
            "P&I $/mo": monthly_pi, "Tax $/mo": monthly_tax, "Ins $/mo": monthly_ins, "PMI/MIP $/mo": pmi_mip,
            "HOA $/mo": hoa, "PITI $/mo": piti, "DTI": dti, "Est Closing Costs $": est_closing_costs,
            "Builder Closing Credit $": closing_credit, "Cash to Close $": cash_to_close, "Program Hint": prog_hint
        })

df = pd.DataFrame(rows)
st.dataframe(df.style.format({
    "Price": "${:,.0f}", "Rate %": "{:.3f}", "Down $": "${:,.0f}", "Loan $": "${:,.0f}", "P&I $/mo": "${:,.0f}",
    "Tax $/mo": "${:,.0f}", "Ins $/mo": "${:,.0f}", "PMI/MIP $/mo": "${:,.0f}", "HOA $/mo": "${:,.0f}",
    "PITI $/mo": "${:,.0f}", "DTI": "{:.1%}", "Est Closing Costs $": "${:,.0f}", "Builder Closing Credit $": "${:,.0f}",
    "Cash to Close $": "${:,.0f}",
}))

st.markdown("---")
st.subheader("Builder vs Outside (P&I only, baseline)")
adj_base = adj_price if inc_type == "PriceReduction" else price
loan_amount_base = max(0.0, adj_base - down_payment)
pi_builder = pmt(rate_builder, loan_term, loan_amount_base)
pi_outside = pmt(rate_outside, loan_term, loan_amount_base)
c1,c2,c3 = st.columns(3)
with c1: st.metric("Builder P&I / mo", currency(pi_builder))
with c2: st.metric("Outside Lender P&I / mo", currency(pi_outside))
with c3: st.metric("Monthly Difference", currency(pi_outside - pi_builder))

# Simple HTML report
st.markdown("---")
st.subheader("Download HTML Report")
if not df.empty:
    sel = st.selectbox("Choose scenario", options=df["Scenario"].tolist())
    r = df[df["Scenario"]==sel].iloc[0].to_dict()
    html = f"""
    <html><head><meta charset='utf-8'></head><body>
    <h2>Mortgage Scenario Report — {r['Scenario']}</h2>
    <ul>
      <li>Price: {currency(r['Price'])}</li>
      <li>Rate: {r['Rate %']:.3f}%</li>
      <li>Loan: {currency(r['Loan $'])}</li>
      <li>PITI: {currency(r['PITI $/mo'])}</li>
      <li>DTI: {r['DTI']*100:.1f}%</li>
      <li>Cash to Close: {currency(r['Cash to Close $'])}</li>
      <li>Program Hint: {r['Program Hint']}</li>
    </ul>
    <p style='font-size:12px;color:#666'>Estimates only. Not a commitment to lend.</p>
    </body></html>
    """
    st.download_button("Download HTML", data=html.encode("utf-8"), file_name="mortgage_report_basic.html", mime="text/html")
st.caption("Basic version")    
