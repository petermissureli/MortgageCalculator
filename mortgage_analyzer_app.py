
import math
import streamlit as st
import pandas as pd

st.set_page_config(page_title="Mortgage & Eligibility Analyzer", page_icon="🏠", layout="wide")

# ---------- Utilities ----------
def pmt(rate_annual_pct, n_years, principal):
    r = (rate_annual_pct/100.0)/12.0
    n = int(n_years*12)
    if r == 0:
        return principal / n if n else 0.0
    return principal * (r * (1 + r)**n) / ((1 + r)**n - 1)

def currency(x):
    return f"${x:,.0f}"

# ---------- Sidebar: Assumptions ----------
with st.sidebar:
    st.header("Assumptions")
    closing_cost_pct = st.number_input("Estimated Closing Costs (% of Price)", value=3.0, step=0.25, min_value=0.0) / 100
    tax_rate = st.number_input("Property Tax Rate (% of Price / year)", value=0.60, step=0.05, min_value=0.0) / 100
    ins_rate = st.number_input("Homeowners Insurance Rate (% of Price / year)", value=0.35, step=0.05, min_value=0.0) / 100
    pmi_rate = st.number_input("PMI (Conventional) Annual Rate (% of balance)", value=0.60, step=0.10, min_value=0.0) / 100
    fha_annual_mip = st.number_input("FHA Annual MIP (% of balance)", value=0.55, step=0.05, min_value=0.0) / 100

    st.markdown("---")
    st.caption("Eligibility thresholds (adjust as needed)")
    min_credit_conv = st.number_input("Min Credit Conventional", value=620, step=10)
    min_credit_fha = st.number_input("Min Credit FHA", value=580, step=10)
    min_credit_va = st.number_input("Min Credit VA", value=580, step=10)
    max_dti_conv = st.number_input("Max DTI Conventional", value=45.0, step=1.0) / 100
    max_dti_fha  = st.number_input("Max DTI FHA", value=50.0, step=1.0) / 100
    max_dti_va   = st.number_input("Max DTI VA", value=55.0, step=1.0) / 100

# ---------- Main Inputs ----------
st.title("🏠 Mortgage & Eligibility Analyzer")
st.caption("Compare builder vs outside lender, apply incentives (price reduction, closing credit, rate buydown), and evaluate program eligibility.")

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
    st.selectbox("USDA Eligible? (not modeled here)", ["No","Yes"])
with elig_cols[2]:
    recent_bk = st.selectbox("Bankruptcy in last 4 yrs?", ["No","Yes"])
with elig_cols[3]:
    recent_fc = st.selectbox("Foreclosure in last 7 yrs?", ["No","Yes"])

st.markdown("---")

# ---------- Incentive Controls ----------
st.subheader("Builder Incentive")
inc_type = st.selectbox("Incentive Type", ["ClosingCredit", "PriceReduction", "RateBuydown"])
inc_amount = st.number_input("Incentive Amount ($)", value=10000, step=1000, min_value=0)

# If RateBuydown, let user directly reduce builder rate
if inc_type == "RateBuydown":
    st.info("Enter the **reduced builder rate** after buydown.")
    rate_builder = st.number_input("Builder Lender Rate After Buydown (%)", value=6.25, step=0.125, min_value=0.0)

# Adjusted price if PriceReduction is chosen
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
        scen_rate = st.number_input("Interest Rate (%)", value=float(base["rate"]), step=0.125, key=f"rate_{i}")
        scen_use_inc = st.selectbox("Use Builder Incentive?", ["Yes","No"], index=0 if base["use_incentive"] else 1, key=f"useinc_{i}")
        scen_down = st.number_input("Down Payment ($)", value=down_payment, step=1000, min_value=0, key=f"down_{i}")

        # Effective price for this scenario
        scen_price = adj_price if (inc_type=="PriceReduction" and scen_use_inc=="Yes") else price
        # Incentive allocated to closing costs (ClosingCredit case)
        closing_credit = inc_amount if (inc_type=="ClosingCredit" and scen_use_inc=="Yes") else 0

        est_closing_costs = scen_price * closing_cost_pct
        loan_amount = max(0.0, scen_price - scen_down)

        monthly_pi = pmt(scen_rate, loan_term, loan_amount)
        monthly_tax = scen_price * tax_rate / 12.0
        monthly_ins = scen_price * ins_rate / 12.0

        ltv = loan_amount / scen_price if scen_price else 0
        # Program hint
        prog_hint = "VA" if va_eligible=="Yes" else ("FHA" if credit_score < min_credit_conv else "Conventional")

        # Simplified PMI/MIP
        if prog_hint == "Conventional" and ltv > 0.80:
            pmi_mip = loan_amount * pmi_rate / 12.0
        elif prog_hint == "FHA":
            pmi_mip = loan_amount * fha_annual_mip / 12.0
        else:
            pmi_mip = 0.0

        piti = monthly_pi + monthly_tax + monthly_ins + hoa + pmi_mip
        dti = (existing_monthly_debts + piti) / gross_monthly_income if gross_monthly_income else 0.0

        conv_ok = (credit_score >= min_credit_conv) and (dti <= max_dti_conv) and (recent_bk=="No") and (recent_fc=="No")
        fha_ok  = (credit_score >= min_credit_fha) and (dti <= max_dti_fha)
        va_ok   = (va_eligible=="Yes") and (credit_score >= min_credit_va) and (dti <= max_dti_va)

        scenario_data.append(dict(
            name=scen_name,
            scen_price=scen_price,
            scen_rate=scen_rate,
            scen_down=scen_down,
            loan_amount=loan_amount,
            monthly_pi=monthly_pi,
            monthly_tax=monthly_tax,
            monthly_ins=monthly_ins,
            hoa=hoa,
            pmi_mip=pmi_mip,
            piti=piti,
            dti=dti,
            closing_credit=closing_credit,
            est_closing_costs=est_closing_costs,
            program_hint=prog_hint,
            conv_ok=conv_ok,
            fha_ok=fha_ok,
            va_ok=va_ok
        ))

# Summary table
df = pd.DataFrame([{
    "Scenario": s["name"],
    "Price": s["scen_price"],
    "Rate %": s["scen_rate"],
    "Down $": s["scen_down"],
    "Loan $": s["loan_amount"],
    "P&I $/mo": s["monthly_pi"],
    "Tax $/mo": s["monthly_tax"],
    "Ins $/mo": s["monthly_ins"],
    "PMI/MIP $/mo": s["pmi_mip"],
    "HOA $/mo": s["hoa"],
    "PITI $/mo": s["piti"],
    "DTI": s["dti"],
    "Est Closing Costs $": s["est_closing_costs"],
    "Builder Closing Credit $": s["closing_credit"],
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
    "P&I $/mo": "${:,.0f}",
    "Tax $/mo": "${:,.0f}",
    "Ins $/mo": "${:,.0f}",
    "PMI/MIP $/mo": "${:,.0f}",
    "HOA $/mo": "${:,.0f}",
    "PITI $/mo": "${:,.0f}",
    "DTI": "{:.1%}",
    "Est Closing Costs $": "${:,.0f}",
    "Builder Closing Credit $": "${:,.0f}",
}))

st.markdown("---")
st.subheader("Builder vs Outside Lender (P&I only)")
adj_base = adj_price if inc_type == "PriceReduction" else price
loan_amount_base = max(0.0, adj_base - down_payment)
pi_builder = pmt(rate_builder, loan_term, loan_amount_base)
pi_outside = pmt(rate_outside, loan_term, loan_amount_base)

c1, c2, c3 = st.columns(3)
with c1: st.metric("Builder P&I / mo", currency(pi_builder))
with c2: st.metric("Outside Lender P&I / mo", currency(pi_outside))
with c3: st.metric("Monthly Difference", currency(pi_outside - pi_builder))

st.subheader("Cash to Close (rough)")
est_close = price * closing_cost_pct
builder_credit = inc_amount if inc_type == "ClosingCredit" else 0
cash_to_close = down_payment + max(0.0, est_close - builder_credit)
st.write(f"**Estimated Closing Costs:** {currency(est_close)}")
st.write(f"**Builder Closing Credit Applied:** {currency(builder_credit)}")
st.write(f"**Estimated Cash to Close:** {currency(cash_to_close)}")

st.markdown("---")
st.caption("Estimate only, not a loan offer. Customize assumptions to match your guidelines.")
