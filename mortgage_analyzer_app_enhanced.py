
import math
import io
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Mortgage & Eligibility Analyzer (Enhanced)", page_icon="🏠", layout="wide")

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
    if not first_use:
        if down_frac < 0.05: return 0.036
        if down_frac < 0.10: return 0.0175
        return 0.015
    if down_frac < 0.05: return 0.0215
    if down_frac < 0.10: return 0.015
    return 0.0125

def present_value_of_diffs(diffs, base_rate_pct):
    i = (base_rate_pct/100.0)/12.0
    pv, m = 0.0, 0
    for months, diff in diffs:
        for _ in range(months):
            m += 1
            pv += (diff / ((1+i)**m)) if i>0 else diff
    return pv

# Sidebar
with st.sidebar:
    st.header("Assumptions & Overlays")
    closing_cost_pct = st.number_input("Estimated Closing Costs (% of Price)", value=3.0, step=0.25, min_value=0.0) / 100
    tax_rate = st.number_input("Property Tax Rate (% of Price / year)", value=0.60, step=0.05, min_value=0.0) / 100
    ins_rate = st.number_input("Homeowners Insurance (% of Price / year)", value=0.35, step=0.05, min_value=0.0) / 100
    pmi_rate = st.number_input("PMI (Conventional) Annual Rate (% of balance)", value=0.60, step=0.10, min_value=0.0) / 100
    fha_ufmip_pct = st.number_input("FHA Upfront MIP (% of loan)", value=1.75, step=0.10, min_value=0.0) / 100
    fha_annual_mip = st.number_input("FHA Annual MIP (% of balance)", value=0.55, step=0.05, min_value=0.0) / 100

    st.caption("Eligibility overlays")
    min_credit_conv = st.number_input("Min Credit Conventional", value=620, step=10)
    min_credit_fha = st.number_input("Min Credit FHA", value=580, step=10)
    min_credit_va = st.number_input("Min Credit VA", value=580, step=10)
    max_dti_conv = st.number_input("Max DTI Conventional", value=45.0, step=1.0) / 100
    max_dti_fha  = st.number_input("Max DTI FHA", value=50.0, step=1.0) / 100
    max_dti_va   = st.number_input("Max DTI VA", value=55.0, step=1.0) / 100

    st.caption("Pricing knobs")
    points_pct = st.number_input("Discount/Origination Points (% of loan)", value=0.00, step=0.125, min_value=0.0) / 100
    rate_reduction_per_point = st.number_input("Rate Reduction per 1.0 Point (bps)", value=25, step=5, min_value=0) / 100
    apply_points_to_builder_rate = st.checkbox("Apply points to Builder rate", value=False)

st.title("🏠 Mortgage & Eligibility Analyzer — Enhanced")

colA,colB,colC = st.columns(3)
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

elig_cols = st.columns(4)
with elig_cols[0]:
    va_eligible = st.selectbox("VA Eligible?", ["No","Yes"])
with elig_cols[1]:
    va_first_use = st.selectbox("VA First Use?", ["Yes","No"])
with elig_cols[2]:
    recent_bk = st.selectbox("Bankruptcy in last 4 yrs?", ["No","Yes"])
with elig_cols[3]:
    recent_fc = st.selectbox("Foreclosure in last 7 yrs?", ["No","Yes"])

st.subheader("Builder Incentive")
inc_type = st.selectbox("Incentive Type", ["ClosingCredit", "PriceReduction", "RateBuydown"])
inc_amount = st.number_input("Incentive Amount ($)", value=10000, step=1000, min_value=0)
buydown_scheme = "Permanent"
if inc_type == "RateBuydown":
    buydown_scheme = st.selectbox("Buydown Scheme", ["Permanent", "2-1", "3-2-1"])
    if buydown_scheme == "Permanent":
        st.info("Enter the reduced builder rate after buydown")
        rate_builder = st.number_input("Builder Rate After Permanent Buydown (%)", value=6.25, step=0.125, min_value=0.0)

if apply_points_to_builder_rate and points_pct > 0:
    rate_builder = max(0.0, rate_builder - (rate_reduction_per_point * (points_pct*100)))

adj_price = price - inc_amount if inc_type == "PriceReduction" else price

# Scenarios: 3 internal + 1 external
st.markdown("### Scenarios (3 Internal + 1 External)")
base_scenarios = [
    {"name": "Internal A – Price Reduction", "rate": rate_builder, "use_incentive": True, "force_type": "PriceReduction"},
    {"name": "Internal B – Closing Credit", "rate": rate_builder, "use_incentive": True, "force_type": "ClosingCredit"},
    {"name": "Internal C – Rate Buydown", "rate": rate_builder, "use_incentive": True, "force_type": "RateBuydown"},
    {"name": "External – Outside Lender", "rate": rate_outside, "use_incentive": False, "force_type": None},
]

rows = []
details = {}
for i, s in enumerate(base_scenarios, start=1):
    with st.expander(s["name"], expanded=(i==1)):
        name = st.text_input("Scenario Name", value=s["name"], key=f"name_{i}")
        rate = st.number_input("Note Rate (%)", value=float(s["rate"]), step=0.125, key=f"rate_{i}")
        use_inc = st.selectbox("Use Builder Incentive?", ["Yes","No"], index=0 if s["use_incentive"] else 1, key=f"useinc_{i}")
        dp = st.number_input("Down Payment ($)", value=down_payment, step=1000, min_value=0, key=f"down_{i}")

        eff_type = s["force_type"] if s["force_type"] else inc_type
        scen_price = price
        closing_credit = 0.0
        if eff_type == "PriceReduction" and use_inc == "Yes":
            scen_price = price - inc_amount
        if eff_type == "ClosingCredit" and use_inc == "Yes":
            closing_credit = inc_amount
        if eff_type == "RateBuydown" and use_inc == "Yes" and buydown_scheme == "Permanent":
            rate = rate  # already adjusted above

        base_loan = max(0.0, scen_price - dp)

        # Program hint
        prog = "VA" if va_eligible=="Yes" else ("FHA" if credit_score < min_credit_conv else "Conventional")

        # FHA/VA financed fees
        loan_amount = base_loan
        financed = 0.0
        note = ""
        if prog == "FHA":
            ufmip = base_loan * fha_ufmip_pct
            loan_amount += ufmip
            financed = ufmip
            note = f"FHA UFMIP financed: {currency(ufmip)}"
        elif prog == "VA":
            down_frac = dp / scen_price if scen_price else 0.0
            fee_pct = va_funding_fee_pct(down_frac, first_use=(va_first_use=='Yes'))
            va_fee = base_loan * fee_pct
            loan_amount += va_fee
            financed = va_fee
            note = f"VA Funding Fee ({pct(fee_pct*100)}) financed: {currency(va_fee)}"

        monthly_pi = pmt(rate, loan_term, loan_amount)
        tax = scen_price * tax_rate / 12.0
        ins = scen_price * ins_rate / 12.0
        ltv = loan_amount / scen_price if scen_price else 0.0
        if prog == "Conventional" and ltv > 0.80:
            mi = loan_amount * pmi_rate / 12.0
        elif prog == "FHA":
            mi = loan_amount * fha_annual_mip / 12.0
        else:
            mi = 0.0
        piti = monthly_pi + tax + ins + mi + hoa
        dti = (existing_monthly_debts + piti)/gross_monthly_income if gross_monthly_income else 0.0

        # temp buydown summary
        buydown = None
        if eff_type == "RateBuydown" and use_inc == "Yes" and buydown_scheme in ["2-1", "3-2-1"]:
            diffs = []
            yearly = []
            base_pay = monthly_pi
            if buydown_scheme == "2-1":
                yrs = [rate-2.0, rate-1.0]
            else:
                yrs = [rate-3.0, rate-2.0, rate-1.0]
            for yr, r in enumerate(yrs, start=1):
                pay = pmt(r, loan_term, loan_amount)
                yearly.append((yr, r, pay))
                diffs.append((12, base_pay - pay))
            pv = present_value_of_diffs(diffs, rate)
            buydown = {"scheme": buydown_scheme, "yearly": yearly, "pv_cost": pv}

        est_cc = scen_price * closing_cost_pct + (points_pct * base_loan)
        cash_to_close = dp + max(0.0, est_cc - closing_credit)

        rows.append({
            "Scenario": name, "Price": scen_price, "Rate %": rate, "Down $": dp, "Loan $": loan_amount,
            "P&I $/mo": monthly_pi, "Tax $/mo": tax, "Ins $/mo": ins, "PMI/MIP $/mo": mi, "HOA $/mo": hoa,
            "PITI $/mo": piti, "DTI": dti, "Est Closing Costs $": est_cc, "Closing Credit $": closing_credit,
            "Cash to Close $": cash_to_close, "Program Hint": prog
        })
        details[name] = {"financed_note": note, "buydown": buydown}

df = pd.DataFrame(rows)
st.dataframe(df.style.format({
    "Price": "${:,.0f}", "Rate %": "{:.3f}", "Down $": "${:,.0f}", "Loan $": "${:,.0f}",
    "P&I $/mo": "${:,.0f}", "Tax $/mo": "${:,.0f}", "Ins $/mo": "${:,.0f}", "PMI/MIP $/mo": "${:,.0f}",
    "HOA $/mo": "${:,.0f}", "PITI $/mo": "${:,.0f}", "DTI": "{:.1%}", "Est Closing Costs $": "${:,.0f}",
    "Closing Credit $": "${:,.0f}", "Cash to Close $": "${:,.0f}",
}))

st.markdown("---")
st.subheader("Download HTML Report")
if not df.empty:
    sel = st.selectbox("Choose scenario", options=df["Scenario"].tolist())
    r = df[df["Scenario"]==sel].iloc[0].to_dict()
    extra = details.get(sel, {})
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
    <p>{extra.get('financed_note','')}</p>
    """
    bd = extra.get("buydown")
    if bd:
        yr = "".join([f"<li>Year {y}: {rt:.3f}% → P&I {currency(p)}</li>" for (y,rt,p) in bd["yearly"]])
        html += f"<h3>Temporary Buydown ({bd['scheme']})</h3><ul>{yr}</ul><p>PV Cost: {currency(bd['pv_cost'])}</p>"
    html += "<p style='font-size:12px;color:#666'>Estimates only. Not a commitment to lend.</p></body></html>"
    st.download_button("Download HTML", data=html.encode("utf-8"), file_name="mortgage_report_enhanced.html", mime="text/html")
st.caption("Enhanced version")    
