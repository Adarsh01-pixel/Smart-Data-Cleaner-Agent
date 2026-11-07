
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import cleaning_engine as ce
import hashlib
import io


# =====================================================
# 1. PAGE CONFIGURATION
# =====================================================

st.set_page_config(
    page_title="Smart Data Cleaner Agent",
    page_icon="🧹",
    layout="wide"
)


# =====================================================
# 2. CUSTOM CSS
# =====================================================

st.markdown("""
<style>
.block-container {
    padding-top: 1.5rem;
    padding-bottom: 2rem;
}

.main-title {
    font-size: clamp(24px, 3vw, 38px);
    font-weight: 700;
    line-height: 1.4;
    white-space: normal;
    overflow: visible;
    display: block;
    padding-top: 10px;
    margin-bottom: 10px;
}

.sub-title {
    color: #64748b;
    font-size: 15px;
}

.metric-card {
    background-color: white;
    padding: 18px;
    border-radius: 12px;
    border: 1px solid #e2e8f0;
}

</style>
""", unsafe_allow_html=True)


# =====================================================
# 3. HEADER
# =====================================================

st.markdown(
    """
    <h1 class="main-title">
        🧹 Smart Data Cleaner Agent
    </h1>
    """,
    unsafe_allow_html=True
)

st.markdown(
    '<div class="sub-title">'
    'Upload, analyze, clean, validate and export your dataset.'
    '</div>',
    unsafe_allow_html=True
)

st.divider()


# =====================================================
# 4. SESSION STATE
# =====================================================

default_values = {
    "raw_df": None,
    "cleaned_df": None,
    "validation_report": None,
    "uploaded_file_hash": None,
    "cleaning_done": False,
    "correction_saved_message": False,
    "initial_validation_df": None,
    "initial_validation_report": None
}

for key, value in default_values.items():

    if key not in st.session_state:
        st.session_state[key] = value


# =====================================================
# 5. HELPER FUNCTIONS
# =====================================================

def align_original_series(current_df, original_df, column):
    """Align a raw source column to current rows using Order_ID when possible."""
    if column not in original_df.columns:
        return pd.Series(index=current_df.index, dtype="object")

    if (
        "Order_ID" in current_df.columns
        and "Order_ID" in original_df.columns
        and original_df["Order_ID"].notna().all()
        and original_df["Order_ID"].is_unique
    ):
        lookup = original_df.set_index("Order_ID")[column]
        return current_df["Order_ID"].map(lookup).set_axis(current_df.index)

    return original_df[column].reindex(current_df.index)


def validate_and_store(df):
    validated_df, report_df = ce.validate_dataset(df)
    report_df = report_df.copy()

    # A date problem must also make the overall record status require review.
    if "Date_Review_Status" in validated_df.columns:
        date_flag = validated_df["Date_Review_Status"].astype(str).eq(
            "Manual Review Required"
        )
        validated_df.loc[date_flag, "Review_Status"] = "Manual Review Required"

    # Do not report a sales-calculation mismatch when an input itself is
    # negative. Those records are already covered by the negative-value rules.
    required = {"Quantity", "Unit_Price", "Total_Sales"}
    if required.issubset(validated_df.columns):
        quantity = pd.to_numeric(validated_df["Quantity"], errors="coerce")
        price = pd.to_numeric(validated_df["Unit_Price"], errors="coerce")
        sales = pd.to_numeric(validated_df["Total_Sales"], errors="coerce")
        mismatch_count = int((
            quantity.notna() & price.notna() & sales.notna()
            & quantity.ge(0) & price.ge(0)
            & ((sales - quantity * price).abs() > 0.01)
        ).sum())
        report_df = report_df[report_df["Issue"] != "Total Sales Mismatch"]
        if mismatch_count:
            report_df = pd.concat([report_df, pd.DataFrame([{
                "Issue": "Total Sales Mismatch",
                "Column": "Total_Sales",
                "Count": mismatch_count
            }])], ignore_index=True)

    # Any missing source field makes its record incomplete and subject to review.
    # Business-critical numeric fields are never imputed automatically.
    # Exclude status/audit fields created by this application.
    generated_columns = {"Review_Status", "Date_Review_Status", "Original_Order_Date"}
    for column in validated_df.columns:
        if column in generated_columns:
            continue

        # Order_Date is handled separately below. The cleaning engine may
        # convert invalid date strings to NaT, so treating every NaT here as
        # "Missing Order_Date" would double-count invalid dates.
        if column == "Order_Date":
            continue

        missing_mask = validated_df[column].isna()
        missing_count = int(missing_mask.sum())
        issue_name = (
            "Missing Quantity" if column == "Quantity" else
            "Missing Unit Price" if column == "Unit_Price" else
            f"Missing {column}"
        )
        report_df = report_df[report_df["Issue"] != issue_name]
        if missing_count:
            report_df = pd.concat([report_df, pd.DataFrame([{
                "Issue": issue_name, "Column": column, "Count": missing_count
            }])], ignore_index=True)
            validated_df.loc[missing_mask, "Review_Status"] = "Manual Review Required"

    # Preserve the distinction between source values that were missing and
    # source values that were present but invalid (e.g. 'invalid_date').
    if "Order_Date" in validated_df.columns:
        source_dates = align_original_series(
            validated_df, st.session_state.raw_df, "Order_Date"
        )
        current_dates = pd.to_datetime(validated_df["Order_Date"], errors="coerce")
        source_parsed = pd.to_datetime(source_dates, errors="coerce")
        unresolved = current_dates.isna()
        invalid_count = int((unresolved & source_dates.notna() & source_parsed.isna()).sum())
        missing_count = int((unresolved & ~(source_dates.notna() & source_parsed.isna())).sum())

        report_df = report_df[~report_df["Issue"].isin(["Invalid Dates", "Missing Dates"])]
        date_rows = []
        if invalid_count:
            date_rows.append({"Issue": "Invalid Dates", "Column": "Order_Date", "Count": invalid_count})
        if missing_count:
            date_rows.append({"Issue": "Missing Dates", "Column": "Order_Date", "Count": missing_count})
        if date_rows:
            report_df = pd.concat([report_df, pd.DataFrame(date_rows)], ignore_index=True)

    report_df = report_df.reset_index(drop=True)
    st.session_state.cleaned_df = validated_df
    st.session_state.validation_report = report_df
    return validated_df, report_df



def get_review_mask(df):

    # Start with statuses returned by the cleaning engine.
    mask = pd.Series(False, index=df.index)

    if "Review_Status" in df.columns:
        mask |= df["Review_Status"].astype(str).eq(
            "Manual Review Required"
        )

    if "Date_Review_Status" in df.columns:
        mask |= df["Date_Review_Status"].astype(str).eq(
            "Manual Review Required"
        )

    # Any missing source field makes the row incomplete and flagged.
    # Exclude status/audit fields created by this application.
    source_columns = [
        column for column in df.columns
        if column not in {"Review_Status", "Date_Review_Status", "Original_Order_Date"}
    ]
    if source_columns:
        mask |= df[source_columns].isna().any(axis=1)

    # Explicitly include negative business-critical numeric values.
    if "Quantity" in df.columns:
        quantity = pd.to_numeric(df["Quantity"], errors="coerce")
        mask |= quantity.lt(0)

    if "Unit_Price" in df.columns:
        unit_price = pd.to_numeric(df["Unit_Price"], errors="coerce")
        mask |= unit_price.lt(0)

    # Date validation must use the current value plus the original source.
    # This catches both invalid strings converted to NaT and truly missing dates.
    if "Order_Date" in df.columns:
        current_dates = pd.to_datetime(df["Order_Date"], errors="coerce")
        date_mask = current_dates.isna()

        source_df = st.session_state.get("raw_df")
        if source_df is not None and "Order_Date" in source_df.columns:
            source_dates = align_original_series(
                df, source_df, "Order_Date"
            )
            # Both missing and invalid source dates require manual review.
            date_mask |= current_dates.isna() & (
                source_dates.isna()
                | pd.to_datetime(source_dates, errors="coerce").isna()
            )

        mask |= date_mask

    return mask


def get_review_reasons(row):
    reasons = []
    quantity = pd.to_numeric(row.get("Quantity"), errors="coerce")
    unit_price = pd.to_numeric(row.get("Unit_Price"), errors="coerce")
    total_sales = pd.to_numeric(row.get("Total_Sales"), errors="coerce")

    # Report all missing source fields, not only the numeric business fields.
    generated_columns = {"Review_Status", "Date_Review_Status", "Original_Order_Date"}
    for column, value in row.items():
        if column not in generated_columns and pd.isna(value):
            if column == "Quantity":
                reasons.append("Missing Quantity")
            elif column == "Unit_Price":
                reasons.append("Missing Unit Price")
            elif column == "Order_Date":
                # Date-specific logic below distinguishes missing from invalid.
                continue
            else:
                reasons.append(f"Missing {column}")

    if pd.notna(quantity) and quantity < 0:
        reasons.append("Negative Quantity")

    if pd.notna(unit_price) and unit_price < 0:
        reasons.append("Negative Unit Price")

    # Only compare sales when both inputs are non-negative and valid.
    if (pd.notna(quantity) and pd.notna(unit_price) and pd.notna(total_sales)
            and quantity >= 0 and unit_price >= 0):
        if abs(total_sales - quantity * unit_price) > 0.01:
            reasons.append("Total Sales Mismatch")

    if "Order_Date" in row.index and pd.isna(
        pd.to_datetime(row["Order_Date"], errors="coerce")
    ):
        original_date = None
        source_df = st.session_state.get("raw_df")

        if source_df is not None and "Order_Date" in source_df.columns:
            if (
                "Order_ID" in row.index
                and "Order_ID" in source_df.columns
                and source_df["Order_ID"].is_unique
            ):
                matching = source_df.loc[
                    source_df["Order_ID"] == row.get("Order_ID"), "Order_Date"
                ]
                if not matching.empty:
                    original_date = matching.iloc[0]
            elif row.name in source_df.index:
                original_date = source_df.loc[row.name, "Order_Date"]

        if pd.isna(original_date):
            reasons.append("Missing Date")
        elif pd.isna(pd.to_datetime(original_date, errors="coerce")):
            reasons.append("Invalid Date")
        else:
            reasons.append("Missing Date")

    return ", ".join(reasons) if reasons else "Requires review"



def create_doughnut_chart(valid_count, flagged_count):

    total = valid_count + flagged_count

    fig = go.Figure()

    if total == 0:

        fig.add_annotation(
            text="No records available",
            x=0.5,
            y=0.5,
            showarrow=False
        )

    else:

        quality = (valid_count / total) * 100

        fig.add_trace(
            go.Pie(
                labels=[
                    "Valid Records",
                    "Flagged Records"
                ],
                values=[
                    valid_count,
                    flagged_count
                ],
                hole=0.75,
                rotation=270,
                sort=False,
                textinfo="none",
                hovertemplate=(
                    "<b>%{label}</b><br>"
                    "Records: %{value}<br>"
                    "Percentage: %{percent}"
                    "<extra></extra>"
                ),
                marker=dict(
                    colors=[
                        "#16a34a",
                        "#ef4444"
                    ],
                    line=dict(
                        width=1,
                        color="rgba(128,128,128,0.2)"
                    )
                ),
                showlegend=False
            )
        )

        fig.add_annotation(
            text=f"<b>{quality:.1f}%</b>",
            x=0.5,
            y=0.5,
            showarrow=False,
            font=dict(size=19)
        )

    fig.update_layout(
        width=220,
        height=220,
        margin=dict(
            l=0,
            r=0,
            t=0,
            b=0
        ),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        showlegend=False
    )

    return fig


def add_original_date_column(export_df, original_df):
    """Add the untouched source date text beside the parsed working date."""
    result = export_df.copy()

    if "Order_Date" in result.columns and original_df is not None:
        original_dates = align_original_series(
            result, original_df, "Order_Date"
        )
        # Store source values as text so Excel does not coerce invalid strings
        # such as 'invalid_date' or '2026-15-40' into blank date cells.
        result["Original_Order_Date"] = original_dates.map(
            lambda value: "" if pd.isna(value) else str(value)
        )

    return result


def create_excel_report(
    cleaned_df,
    report_df,
    review_df,
    original_df=None
):

    output = io.BytesIO()
    export_cleaned_df = add_original_date_column(cleaned_df, original_df)
    export_review_df = add_original_date_column(review_df, original_df)

    with pd.ExcelWriter(
        output,
        engine="openpyxl"
    ) as writer:

        export_cleaned_df.to_excel(
            writer,
            sheet_name="Cleaned Data",
            index=False
        )

        report_df.to_excel(
            writer,
            sheet_name="Validation Report",
            index=False
        )

        export_review_df.to_excel(
            writer,
            sheet_name="Manual Review",
            index=False
        )

    output.seek(0)

    return output


def get_validation_count(report_df, issue_name):

    if (
        report_df is None
        or report_df.empty
        or "Issue" not in report_df.columns
        or "Count" not in report_df.columns
    ):
        return 0

    matching = report_df[
        report_df["Issue"].astype(str).str.strip()
        == issue_name
    ]

    if matching.empty:
        return 0

    return int(
        pd.to_numeric(
            matching["Count"],
            errors="coerce"
        ).fillna(0).sum()
    )


# =====================================================
# 6. RULE-WISE VALIDATION DETAILS
# =====================================================

def get_rule_details(rule, current_df, original_df):

    df = current_df.copy()

    original_dates_aligned = align_original_series(df, original_df, "Order_Date")

    details = []

    # -------------------------------------------------
    # NEGATIVE QUANTITY
    # -------------------------------------------------

    if rule == "Negative Quantity":

        if "Quantity" not in df.columns:
            return pd.DataFrame()

        quantity = pd.to_numeric(
            df["Quantity"],
            errors="coerce"
        )

        mask = quantity < 0

        for idx in df.index[mask]:

            details.append({
                "Record ID": df.loc[idx].get("Order_ID", idx),
                "Customer": df.loc[idx].get("Customer_Name", ""),
                "Problematic Column": "Quantity",
                "Problematic Value": quantity.loc[idx],
                "Reason": "Quantity cannot be negative.",
                "Suggested Correction": (
                    "Verify the original order quantity "
                    "and enter the correct value."
                )
            })

    # -------------------------------------------------
    # NEGATIVE UNIT PRICE
    # -------------------------------------------------

    elif rule == "Negative Unit Price":

        if "Unit_Price" not in df.columns:
            return pd.DataFrame()

        unit_price = pd.to_numeric(
            df["Unit_Price"],
            errors="coerce"
        )

        mask = unit_price < 0

        for idx in df.index[mask]:

            details.append({
                "Record ID": df.loc[idx].get("Order_ID", idx),
                "Customer": df.loc[idx].get("Customer_Name", ""),
                "Problematic Column": "Unit_Price",
                "Problematic Value": unit_price.loc[idx],
                "Reason": "Unit price cannot be negative.",
                "Suggested Correction": (
                    "Verify the original invoice or product price "
                    "and enter the correct value."
                )
            })

    # -------------------------------------------------
    # MISSING BUSINESS-CRITICAL INPUTS
    # -------------------------------------------------

    elif rule in ("Missing Quantity", "Missing Unit Price"):
        column = "Quantity" if rule == "Missing Quantity" else "Unit_Price"
        if column not in df.columns:
            return pd.DataFrame()
        for idx in df.index[df[column].isna()]:
            details.append({
                "Record ID": df.loc[idx].get("Order_ID", idx),
                "Customer": df.loc[idx].get("Customer_Name", ""),
                "Problematic Column": column,
                "Problematic Value": "Missing",
                "Reason": f"{column} is missing, so the transaction value cannot be verified.",
                "Suggested Correction": (
                    "Verify the original transaction record or invoice and enter the confirmed value. "
                    "Do not infer it from Total_Sales."
                )
            })

    # -------------------------------------------------
    # TOTAL SALES MISMATCH
    # -------------------------------------------------

    elif rule == "Total Sales Mismatch":

        required = [
            "Quantity",
            "Unit_Price",
            "Total_Sales"
        ]

        if not all(col in df.columns for col in required):
            return pd.DataFrame()

        quantity = pd.to_numeric(
            df["Quantity"],
            errors="coerce"
        )

        unit_price = pd.to_numeric(
            df["Unit_Price"],
            errors="coerce"
        )

        total_sales = pd.to_numeric(
            df["Total_Sales"],
            errors="coerce"
        )

        expected = quantity * unit_price

        mask = (
            quantity.notna()
            & unit_price.notna()
            & total_sales.notna()
            & quantity.ge(0)
            & unit_price.ge(0)
            & ((total_sales - expected).abs() > 0.01)
        )

        for idx in df.index[mask]:

            if (
                quantity.loc[idx] < 0
                or unit_price.loc[idx] < 0
            ):

                suggestion = (
                    "First verify Quantity and Unit_Price. "
                    "Recalculate Total_Sales only after "
                    "confirming both values."
                )

            else:

                suggestion = (
                    f"Verify the inputs, then check whether "
                    f"Total_Sales should be "
                    f"{expected.loc[idx]:.2f}."
                )

            details.append({
                "Record ID": df.loc[idx].get("Order_ID", idx),
                "Customer": df.loc[idx].get("Customer_Name", ""),
                "Problematic Column": "Total_Sales",
                "Actual Value": total_sales.loc[idx],
                "Expected Value": expected.loc[idx],
                "Reason": (
                    "Total Sales should equal "
                    "Quantity × Unit Price."
                ),
                "Suggested Correction": suggestion
            })

    # -------------------------------------------------
    # MISSING DATES
    # -------------------------------------------------

    elif rule == "Missing Dates":

        if "Order_Date" not in df.columns:
            return pd.DataFrame()

        current_dates = pd.to_datetime(
            df["Order_Date"],
            errors="coerce"
        )

        original_dates = original_dates_aligned

        original_parsed = pd.to_datetime(original_dates, errors="coerce")
        mask = current_dates.isna() & ~(
            original_dates.notna() & original_parsed.isna()
        )

        for idx in df.index[mask]:

            details.append({
                "Record ID": df.loc[idx].get("Order_ID", idx),
                "Customer": df.loc[idx].get("Customer_Name", ""),
                "Problematic Column": "Order_Date",
                "Problematic Value": "Missing",
                "Reason": "Order date is missing.",
                "Suggested Correction": (
                    "Enter the correct order date using "
                    "the original transaction record."
                )
            })

    # -------------------------------------------------
    # INVALID DATES
    # -------------------------------------------------

    elif rule == "Invalid Dates":

        if "Order_Date" not in df.columns:
            return pd.DataFrame()

        current_dates = pd.to_datetime(
            df["Order_Date"],
            errors="coerce"
        )

        original_dates = original_dates_aligned

        original_parsed = pd.to_datetime(
            original_dates,
            errors="coerce"
        )

        mask = (
            current_dates.isna()
            & original_dates.notna()
            & original_parsed.isna()
        )

        for idx in df.index[mask]:

            details.append({
                "Record ID": df.loc[idx].get("Order_ID", idx),
                "Customer": df.loc[idx].get("Customer_Name", ""),
                "Problematic Column": "Order_Date",
                "Problematic Value": str(original_dates.loc[idx]),
                "Reason": (
                    "Date value is not in a valid date format."
                ),
                "Suggested Correction": (
                    "Check the original transaction record "
                    "and enter the date in YYYY-MM-DD format."
                )
            })

    return pd.DataFrame(details)


# =====================================================
# 7. SIDEBAR
# =====================================================

with st.sidebar:

    st.title("🧹 Data Cleaner")

    st.markdown("---")

    st.subheader("Project Features")

    st.write("📂 CSV / Excel Upload")
    st.write("📊 Data Profiling")
    st.write("🔍 Issue Detection")
    st.write("🛠️ Smart Cleaning")
    st.write("✅ Data Validation")
    st.write("🔬 Advanced Data Validation")
    st.write("✏️ Manual Corrections")
    st.write("📥 CSV / Excel Export")

    st.markdown("---")

    if st.button(
        "Reset Application",
        width="stretch"
    ):

        for key in default_values:
            st.session_state[key] = default_values[key]

        st.rerun()


# =====================================================
# 8. FILE UPLOAD
# =====================================================

uploaded_file = st.file_uploader(
    "Upload your dataset",
    type=["csv", "xlsx"],
    help="Upload a CSV or Excel dataset."
)

if uploaded_file is None:

    st.info("Upload a CSV or Excel file to begin.")

    st.stop()


# =====================================================
# 9. READ DATASET
# =====================================================

file_bytes = uploaded_file.getvalue()

file_hash = hashlib.md5(file_bytes).hexdigest()

if file_hash != st.session_state.uploaded_file_hash:

    try:

        if uploaded_file.name.lower().endswith(".csv"):

            df = pd.read_csv(
                io.BytesIO(file_bytes)
            )

        else:

            df = pd.read_excel(
                io.BytesIO(file_bytes)
            )

        st.session_state.raw_df = df.copy()
        st.session_state.cleaned_df = None
        st.session_state.validation_report = None
        st.session_state.initial_validation_df = None
        st.session_state.initial_validation_report = None
        st.session_state.cleaning_done = False
        st.session_state.uploaded_file_hash = file_hash

    except Exception as e:

        st.error(f"Unable to read file: {e}")
        st.stop()


raw_df = st.session_state.raw_df

# Always initialize validation for a newly uploaded dataset.
# Clean datasets with no cleaning recommendations can therefore display
# their data-quality score immediately.
if st.session_state.cleaned_df is None:
    try:
        validate_and_store(raw_df.copy())
    except Exception as e:
        st.error(f"Initial data validation error: {e}")
        st.stop()

if st.session_state.initial_validation_df is None:
    st.session_state.initial_validation_df = st.session_state.cleaned_df.copy()
    st.session_state.initial_validation_report = st.session_state.validation_report.copy()


# =====================================================
# 10. DATASET OVERVIEW
# =====================================================

st.header("1. Dataset Overview")

col1, col2, col3 = st.columns(3)

with col1:
    st.metric("Total Rows", f"{raw_df.shape[0]:,}")

with col2:
    st.metric("Total Columns", f"{raw_df.shape[1]:,}")

with col3:
    st.metric(
        "Missing Values",
        f"{raw_df.isnull().sum().sum():,}"
    )


with st.expander("Preview Original Dataset", expanded=True):

    st.dataframe(
        raw_df.head(10),
        width="stretch"
    )


# =====================================================
# 11. DATA PROFILING
# =====================================================

st.header("2. Data Profiling")

try:

    profile = ce.generate_data_profile(raw_df)

    st.subheader("Column Profile")

    if isinstance(profile, pd.DataFrame):
        st.dataframe(profile, width="stretch")
    else:
        st.write(profile)

except Exception as e:

    st.warning(f"Could not generate data profile: {e}")


try:

    summary = ce.generate_dataset_summary(raw_df)

    st.subheader("Dataset Summary")
    st.write(summary)

except Exception as e:

    st.warning(f"Could not generate dataset summary: {e}")


# =====================================================
# 12. INITIAL DATA VALIDATION (BEFORE CLEANING)
# =====================================================

st.divider()
st.header("3. Initial Data Validation")
st.caption("Baseline data quality before applying any cleaning actions.")

initial_df = st.session_state.initial_validation_df
initial_report = st.session_state.initial_validation_report
initial_review_mask = get_review_mask(initial_df)
initial_total = len(initial_df)
initial_flagged = int(initial_review_mask.sum())
initial_valid = initial_total - initial_flagged
initial_quality = (initial_valid / initial_total * 100) if initial_total else 0

initial_col1, initial_col2, initial_col3, initial_col4 = st.columns(4)
with initial_col1:
    st.metric("Total Records", f"{initial_total:,}")
with initial_col2:
    st.metric("Valid Records", f"{initial_valid:,}")
with initial_col3:
    st.metric("Flagged Records", f"{initial_flagged:,}")
with initial_col4:
    st.metric("Initial Data Quality", f"{initial_quality:.1f}%")

st.subheader("Initial Validation Issue Report")
if initial_report is not None and not initial_report.empty:
    st.dataframe(initial_report, width="stretch", hide_index=True)
else:
    st.success("No validation issues detected in the original dataset.")


# =====================================================
# 13. CLEANING RECOMMENDATIONS
# =====================================================

st.divider()

st.header("4. Smart Cleaning Recommendations")

try:

    recommendations = ce.generate_cleaning_recommendations(
        raw_df
    )

    if recommendations is None or recommendations.empty:

        st.success("No cleaning recommendations detected.")

    else:

        st.dataframe(
            recommendations,
            width="stretch",
            hide_index=True
        )

        st.subheader("Approve Cleaning Actions")

        approved_actions = []

        for index, row in recommendations.iterrows():

            column = row["Column Name"]
            issue = str(row["Issue"])

            st.markdown(
                f"**{index + 1}. {column} — {issue}**"
            )

            method_options = []

            if "Duplicate" in issue:

                method_options = ["remove_duplicates"]

            elif "Missing" in issue:

                if column in raw_df.columns:

                    if column in ["Quantity", "Unit_Price", "Total_Sales"]:
                        method_options = []
                    elif pd.api.types.is_numeric_dtype(raw_df[column]):
                        method_options = ["median", "mean"]
                    else:
                        method_options = ["mode"]

            elif "Inconsistent Text" in issue:

                method_options = ["standardize_text"]

            elif "Date" in issue:

                method_options = ["convert_invalid_dates"]

            if method_options:

                selected_method = st.selectbox(
                    "Cleaning method",
                    method_options,
                    key=f"method_{index}"
                )

                approved = st.checkbox(
                    "Approve this cleaning action",
                    key=f"approve_{index}"
                )

                if approved:

                    approved_actions.append({
                        "column": column,
                        "method": selected_method
                    })

            else:
                if "Missing" in issue and column in ["Quantity", "Unit_Price", "Total_Sales"]:
                    st.warning(
                        f"{column} is a business-critical value. It will not be filled automatically. "
                        "Verify it from the original transaction record and correct it in Manual Data Correction."
                    )
                else:
                    st.caption("No automatic cleaning method is available.")

            st.markdown("---")

        if st.button(
            "Apply Approved Cleaning Actions",
            type="primary",
            width="stretch"
        ):

            if approved_actions:

                try:

                    cleaned = ce.apply_cleaning_actions(
                        raw_df.copy(),
                        approved_actions
                    )

                    validate_and_store(cleaned)

                    st.session_state.cleaning_done = True

                    st.success("Approved cleaning actions applied.")

                    st.rerun()

                except Exception as e:

                    st.error(f"Cleaning error: {e}")

            else:

                st.warning(
                    "Approve at least one cleaning action first."
                )


except Exception as e:

    st.error(f"Recommendation error: {e}")


# =====================================================
# CHECK CLEANED DATA
# =====================================================

if st.session_state.cleaned_df is None:

    st.info(
        "Initial validation is available above. Apply approved cleaning actions "
        "to update the final validation results."
    )

    st.stop()


cleaned_df = st.session_state.cleaned_df

validation_report = st.session_state.validation_report


# =====================================================
# 14. FINAL DATA VALIDATION
# =====================================================

st.divider()

st.header("5. Final Data Validation")

review_mask = get_review_mask(cleaned_df)

total_records = len(cleaned_df)

flagged_count = int(review_mask.sum())

valid_count = total_records - flagged_count

quality_percentage = (
    (valid_count / total_records) * 100
    if total_records > 0 else 0
)


# =====================================================
# METRIC CARDS
# =====================================================

col1, col2, col3, col4 = st.columns(4)

with col1:
    st.metric("Total Records", f"{total_records:,}")

with col2:
    st.metric("Valid Records", f"{valid_count:,}")

with col3:
    st.metric("Flagged Records", f"{flagged_count:,}")

with col4:
    st.metric("Data Quality", f"{quality_percentage:.1f}%")


# =====================================================
# COMPACT PLOTLY DOUGHNUT CHART
# =====================================================

st.subheader("Dataset Quality")

chart_col1, chart_col2 = st.columns([1, 1.5])

with chart_col1:

    fig = create_doughnut_chart(
        valid_count,
        flagged_count
    )

    st.plotly_chart(
        fig,
        width="content",
        config={
            "displayModeBar": False,
            "responsive": True
        }
    )


with chart_col2:

    st.markdown("#### Quality Breakdown")

    valid_percentage = (
        valid_count / total_records * 100
        if total_records else 0
    )

    flagged_percentage = (
        flagged_count / total_records * 100
        if total_records else 0
    )

    st.markdown(
        f"🟢 **Valid Records:** {valid_count:,} "
        f"({valid_percentage:.1f}%)"
    )

    st.markdown(
        f"🔴 **Flagged Records:** {flagged_count:,} "
        f"({flagged_percentage:.1f}%)"
    )

    st.progress(
        int(round(quality_percentage))
    )

    st.caption(
        "Percentage of records passing validation."
    )


st.caption(
    "A record is counted once as flagged, even if it contains "
    "multiple validation issues."
)


# =====================================================
# 14. VALIDATION ISSUE REPORT
# =====================================================

st.subheader("Validation Issue Report")

if validation_report is not None and not validation_report.empty:

    st.dataframe(
        validation_report,
        width="stretch",
        hide_index=True
    )

else:

    st.success("No validation issues detected.")


# =====================================================
# 16. ADVANCED DATA VALIDATION
# =====================================================

st.divider()

st.header("6. Advanced Data Validation")

st.write(
    "Detailed rule-based checks to identify data quality "
    "problems and inspect affected records."
)

validation_rules = [
    "Missing Quantity",
    "Missing Unit Price",
    "Negative Quantity",
    "Negative Unit Price",
    "Total Sales Mismatch",
    "Invalid Dates",
    "Missing Dates"
]

advanced_results = []

for rule in validation_rules:

    issue_count = get_validation_count(
        validation_report,
        rule
    )

    status = (
        "Passed"
        if issue_count == 0
        else "Needs Attention"
    )

    advanced_results.append({
        "Validation Rule": rule,
        "Records Affected": issue_count,
        "Status": status
    })


advanced_df = pd.DataFrame(advanced_results)

passed_count = int(
    (advanced_df["Status"] == "Passed").sum()
)

attention_count = int(
    (advanced_df["Status"] == "Needs Attention").sum()
)


# SUMMARY METRICS

col1, col2 = st.columns(2)

with col1:

    st.metric(
        "Rules Passed",
        f"{passed_count}/{len(validation_rules)}"
    )

with col2:

    st.metric(
        "Rules Requiring Attention",
        f"{attention_count}/{len(validation_rules)}"
    )


# VALIDATION RULE TABLE

st.dataframe(
    advanced_df,
    width="stretch",
    hide_index=True
)


# =====================================================
# 16. COMPACT RULE-WISE VALIDATION DETAILS
# =====================================================

st.subheader("Rule-wise Validation Details")

for rule in validation_rules:

    issue_count = get_validation_count(
        validation_report,
        rule
    )

    if issue_count == 0:

        st.success(
            f"✓ {rule} — No issues detected."
        )

    else:

        with st.expander(
            f"🔴 {rule} — {issue_count} record{'s' if issue_count != 1 else ''} affected"
        ):

            details_df = get_rule_details(
                rule,
                cleaned_df,
                raw_df
            )

            if not details_df.empty:

                for index, row in details_df.iterrows():

                    with st.container(border=True):

                        # RECORD HEADER
                        record_id = row.get(
                            "Record ID",
                            "Unknown"
                        )

                        customer = row.get(
                            "Customer",
                            "Unknown"
                        )

                        st.markdown(
                            f"### Record ID: {record_id} | {customer}"
                        )

                        # PROBLEM DETAILS
                        col1, col2 = st.columns(2)

                        with col1:

                            st.caption("Problematic Column")

                            st.write(
                                row.get(
                                    "Problematic Column",
                                    "-"
                                )
                            )

                        with col2:

                            st.caption("Problematic Value")

                            problematic_value = row.get(
                                "Problematic Value",
                                row.get("Actual Value", "-")
                            )

                            st.write(problematic_value)

                        # ACTUAL AND EXPECTED VALUES
                        if (
                            "Actual Value" in row.index
                            and "Expected Value" in row.index
                        ):

                            col1, col2 = st.columns(2)

                            with col1:

                                st.metric(
                                    "Actual Value",
                                    f"{row['Actual Value']:,.2f}"
                                )

                            with col2:

                                st.metric(
                                    "Expected Value",
                                    f"{row['Expected Value']:,.2f}"
                                )

                        # REASON
                        st.markdown("**Reason**")

                        st.write(
                            row.get("Reason", "-")
                        )

                        # SUGGESTED CORRECTION
                        st.markdown(
                            "**💡 Suggested Correction**"
                        )

                        st.info(
                            row.get(
                                "Suggested Correction",
                                "Verify the original source record."
                            )
                        )

                # DOWNLOAD DETAILS
                st.download_button(
                    label=f"📥 Download {rule} Details",
                    data=details_df.to_csv(
                        index=False
                    ).encode("utf-8"),
                    file_name=(
                        rule.lower().replace(" ", "_")
                        + "_details.csv"
                    ),
                    mime="text/csv",
                    key=f"download_compact_{rule}"
                )

                if len(details_df) != issue_count:
                    st.warning(
                        f"Validation report lists {issue_count} affected record(s), "
                        f"but {len(details_df)} detail card(s) were reconstructed. "
                        "Check the source data and record identifiers."
                    )

            else:

                st.warning(
                    "Affected records could not be reconstructed "
                    "from the available dataset."
                )


if attention_count == 0:

    st.success(
        "All advanced validation rules passed."
    )

else:

    st.warning(
        f"{attention_count} validation rules require attention."
    )


st.caption(
    "Suggested corrections are advisory. Verify original "
    "transaction records before modifying business values."
)


# =====================================================
# 17. MANUAL REVIEW
# =====================================================

st.divider()

st.header("7. Manual Review")

review_df = cleaned_df.loc[review_mask].copy()

if not review_df.empty:

    review_df["Review_Reason"] = review_df.apply(
        get_review_reasons,
        axis=1
    )

    st.warning(
        f"{len(review_df)} records require manual review."
    )

    st.dataframe(
        review_df,
        width="stretch",
        hide_index=True
    )

    review_csv = review_df.to_csv(
        index=False
    ).encode("utf-8")

    st.download_button(
        "Download Manual Review CSV",
        data=review_csv,
        file_name="manual_review.csv",
        mime="text/csv"
    )

else:

    st.success("No records require manual review.")


# =====================================================
# 18. MANUAL DATA CORRECTION
# =====================================================

st.divider()

st.header("8. Manual Data Correction")

# Keep the save confirmation visible after the rerun that refreshes validation.
if st.session_state.get("correction_saved_message", False):
    st.success("Corrections saved successfully. The dataset has been revalidated.")
    st.session_state["correction_saved_message"] = False

if not review_df.empty:

    editable_columns = [
        column for column in [
            "Product",
            "Quantity",
            "Unit_Price",
            "Total_Sales",
            "Order_Date"
        ]
        if column in cleaned_df.columns
    ]

    identity_columns = [
        column for column in ["Order_ID", "Customer_Name"]
        if column in cleaned_df.columns
    ]

    if editable_columns:

        st.write(
            "Edit the flagged records below. Order ID and Customer Name "
            "are shown for identification and cannot be edited. "
            "Your corrections will be validated again."
        )

        # Keep the original dataframe index so edits can be written back safely.
        editable_df = cleaned_df.loc[
            review_mask,
            identity_columns + editable_columns
        ].copy()

        # The cleaning engine converts invalid dates to NaT. For display only,
        # restore the original source text wherever the current date is unresolved.
        if "Order_Date" in editable_df.columns:
            source_dates = align_original_series(
                editable_df, raw_df, "Order_Date"
            )
            current_dates = pd.to_datetime(
                editable_df["Order_Date"], errors="coerce"
            )
            unresolved_with_source_text = (
                current_dates.isna() & source_dates.notna()
            )
            editable_df["Order_Date"] = editable_df["Order_Date"].astype(object)
            editable_df.loc[
                unresolved_with_source_text, "Order_Date"
            ] = source_dates.loc[unresolved_with_source_text].astype(str)

        edited_df = st.data_editor(
            editable_df,
            width="stretch",
            num_rows="fixed",
            disabled=identity_columns,
            key="correction_editor"
        )

        st.caption(
            "Rows are identified by Order_ID and Customer_Name. "
            "Original invalid date text is shown so it is not mistaken for "
            "an ordinary blank date. Enter a verified date in YYYY-MM-DD format."
        )

        if st.button(
            "Save Corrections and Revalidate",
            type="primary"
        ):

            try:
                updated_df = cleaned_df.copy()

                # Convert editor output to the destination column's intended
                # dtype BEFORE assignment. Streamlit's data_editor can return
                # date values as ArrowStringArray even when the source column
                # is datetime64; direct assignment raises an ArrowStringArray
                # to datetime64 TypeError.
                for column in editable_columns:
                    edited_values = edited_df[column].copy()

                    if column == "Order_Date":
                        # Valid user-entered dates become timestamps. Invalid
                        # or unchanged invalid source strings become NaT; raw_df
                        # remains untouched and is used to show the source text.
                        edited_values = pd.to_datetime(
                            edited_values, errors="coerce"
                        )
                    elif column in ["Quantity", "Unit_Price", "Total_Sales"]:
                        edited_values = pd.to_numeric(
                            edited_values, errors="coerce"
                        )

                    updated_df.loc[edited_df.index, column] = edited_values

                # Normalize date dtype after the typed assignment as a final
                # safeguard for mixed/null editor values.
                if "Order_Date" in updated_df.columns:
                    updated_df["Order_Date"] = pd.to_datetime(
                        updated_df["Order_Date"], errors="coerce"
                    )

                validate_and_store(updated_df)

                # Persist the confirmation across Streamlit's rerun. A direct
                # st.success() immediately before st.rerun() disappears too fast.
                st.session_state["correction_saved_message"] = True
                st.rerun()

            except Exception as e:
                st.error(f"Correction error: {e}")

    else:
        st.info("No supported columns are available for manual correction.")

else:
    st.info("No records require manual review.")


# =====================================================
# 19. CLEANED DATASET
# =====================================================

st.divider()

st.header("9. Cleaned Dataset")

st.dataframe(
    st.session_state.cleaned_df.head(20),
    width="stretch"
)


# =====================================================
# 20. EXPORT
# =====================================================

st.divider()

st.header("10. Export Cleaned Dataset")

final_df = st.session_state.cleaned_df

final_report = st.session_state.validation_report

final_review_mask = get_review_mask(final_df)

final_review_df = final_df.loc[
    final_review_mask
].copy()

if not final_review_df.empty:

    final_review_df["Review_Reason"] = (
        final_review_df.apply(
            get_review_reasons,
            axis=1
        )
    )


# Include the untouched source date text in exports. The working Order_Date
# remains datetime/NaT for validation; Original_Order_Date preserves the exact
# source value for auditing and manual correction.
export_final_df = add_original_date_column(final_df, raw_df)
export_review_df = add_original_date_column(final_review_df, raw_df)

csv_data = export_final_df.to_csv(
    index=False
).encode("utf-8")


col1, col2 = st.columns(2)

with col1:

    st.download_button(
        label="📥 Download Cleaned CSV",
        data=csv_data,
        file_name="sales_cleaned_final.csv",
        mime="text/csv",
        width="stretch"
    )


with col2:

    try:

        excel_data = create_excel_report(
            final_df,
            final_report,
            final_review_df,
            raw_df
        )

        st.download_button(
            label="📊 Download Excel Report",
            data=excel_data,
            file_name="data_cleaning_report.xlsx",
            mime=(
                "application/vnd.openxmlformats-officedocument."
                "spreadsheetml.sheet"
            ),
            width="stretch"
        )

    except Exception as e:

        st.warning(
            f"Excel export unavailable: {e}"
        )


# =====================================================
# 21. FOOTER
# =====================================================

st.divider()

st.caption(
    "Smart Data Cleaner Agent | Python | Pandas | "
    "Plotly | Streamlit"
)
