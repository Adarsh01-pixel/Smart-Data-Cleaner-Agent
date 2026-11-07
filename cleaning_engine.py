
import pandas as pd


# =====================================================
# 1. DETECT COLUMN DATA TYPES
# =====================================================

def detect_column_types(df):
    column_types = {}

    for col in df.columns:
        series = df[col].dropna()

        if series.empty:
            column_types[col] = "Empty"

        elif pd.api.types.is_bool_dtype(df[col]):
            column_types[col] = "Boolean"

        elif pd.api.types.is_numeric_dtype(df[col]):
            column_types[col] = "Numeric"

        elif pd.api.types.is_datetime64_any_dtype(df[col]):
            column_types[col] = "Date"

        elif (
            pd.api.types.is_object_dtype(df[col])
            or pd.api.types.is_string_dtype(df[col])
        ):
            name = str(col).lower()

            if any(word in name for word in ["date", "time", "dob"]):
                column_types[col] = "Date"
            else:
                parsed_dates = pd.to_datetime(series, errors="coerce")
                valid_ratio = parsed_dates.notna().mean()

                column_types[col] = (
                    "Date" if valid_ratio >= 0.80 else "Text"
                )

        else:
            column_types[col] = "Other"

    return column_types


# =====================================================
# 2. GENERATE DATA PROFILE
# =====================================================

def generate_data_profile(df):

    column_types = detect_column_types(df)
    profile = []

    for col in df.columns:

        profile.append({
            "Column Name": col,
            "Data Type": column_types[col],
            "Missing Values": int(df[col].isna().sum()),
            "Missing Percentage": round(
                df[col].isna().mean() * 100, 2
            ),
            "Unique Values": int(df[col].nunique()),
            "Duplicate Values": int(df[col].duplicated().sum())
        })

    return pd.DataFrame(profile)


# =====================================================
# 3. GENERATE DATASET SUMMARY
# =====================================================

def generate_dataset_summary(df):

    return {
        "Total Rows": len(df),
        "Total Columns": len(df.columns),
        "Total Missing Values": int(df.isna().sum().sum()),
        "Duplicate Rows": int(df.duplicated().sum()),
        "Memory Usage (KB)": round(
            df.memory_usage(deep=True).sum() / 1024, 2
        )
    }


# =====================================================
# 4. DETECT INCONSISTENT TEXT
# =====================================================

def detect_inconsistent_text(series):

    original_values = series.dropna().astype(str)

    normalized_values = (
        original_values.str.strip().str.lower()
    )

    grouped_values = pd.DataFrame({
        "Original": original_values,
        "Normalized": normalized_values
    })

    inconsistent_count = 0

    for _, group in grouped_values.groupby("Normalized"):

        if group["Original"].nunique() > 1:
            inconsistent_count += len(group)

    return inconsistent_count


# =====================================================
# 5. GENERATE CLEANING RECOMMENDATIONS
# =====================================================

def generate_cleaning_recommendations(df):

    column_types = detect_column_types(df)
    recommendations = []

    duplicate_count = int(df.duplicated().sum())

    if duplicate_count > 0:

        recommendations.append({
            "Column Name": "Entire Dataset",
            "Issue": "Duplicate Records",
            "Count": duplicate_count,
            "Recommendation": "Review and remove exact duplicate rows"
        })

    for col in df.columns:

        missing_count = int(df[col].isna().sum())
        data_type = column_types[col]

        if missing_count > 0:

            if data_type == "Numeric":
                action = "Choose mean or median imputation"

            elif data_type == "Text":
                action = "Choose mode imputation or manual replacement"

            elif data_type == "Date":
                action = "Review missing dates or leave unchanged"

            else:
                action = "Review missing values manually"

            recommendations.append({
                "Column Name": col,
                "Issue": "Missing Values",
                "Count": missing_count,
                "Recommendation": action
            })

        if data_type == "Text":

            inconsistent_count = detect_inconsistent_text(df[col])

            if inconsistent_count > 0:

                recommendations.append({
                    "Column Name": col,
                    "Issue": "Inconsistent Text Formatting",
                    "Count": inconsistent_count,
                    "Recommendation": "Review capitalization and extra spaces"
                })

        if data_type == "Date":

            parsed_dates = pd.to_datetime(
                df[col],
                errors="coerce"
            )

            invalid_count = int(
                (df[col].notna() & parsed_dates.isna()).sum()
            )

            if invalid_count > 0:

                recommendations.append({
                    "Column Name": col,
                    "Issue": "Invalid Dates",
                    "Count": invalid_count,
                    "Recommendation": (
                        "Review invalid dates or convert them to missing values"
                    )
                })

    return pd.DataFrame(
        recommendations,
        columns=[
            "Column Name",
            "Issue",
            "Count",
            "Recommendation"
        ]
    )


# =====================================================
# 6. STANDARDIZE TEXT
# =====================================================

def standardize_text(series):

    abbreviations = {
        "it": "IT",
        "hr": "HR",
        "sql": "SQL",
        "api": "API",
        "ai": "AI",
        "ml": "ML",
        "iot": "IoT",
        "usa": "USA",
        "uk": "UK",
        "html": "HTML",
        "css": "CSS",
        "python": "Python",
        "upi": "UPI",
        "atm": "ATM",
        "pcb": "PCB",
        "ic": "IC"
    }

    def clean_value(value):

        if pd.isna(value):
            return value

        value = str(value).strip()
        key = value.lower()

        if key in abbreviations:
            return abbreviations[key]

        return value.title()

    return series.map(clean_value)


# =====================================================
# 7. APPLY APPROVED CLEANING ACTIONS
# =====================================================

def apply_cleaning_actions(df, approved_actions):

    cleaned_df = df.copy()

    for action in approved_actions:

        column = action["column"]
        method = action["method"]

        if (
            method != "remove_duplicates"
            and column not in cleaned_df.columns
        ):
            continue

        if method == "median":

            numeric_values = pd.to_numeric(
                cleaned_df[column],
                errors="coerce"
            )

            fill_value = numeric_values.median()

            if pd.notna(fill_value):
                cleaned_df[column] = numeric_values.fillna(fill_value)

        elif method == "mean":

            numeric_values = pd.to_numeric(
                cleaned_df[column],
                errors="coerce"
            )

            fill_value = numeric_values.mean()

            if pd.notna(fill_value):
                cleaned_df[column] = numeric_values.fillna(fill_value)

        elif method == "mode":

            mode_values = cleaned_df[column].mode(dropna=True)

            if not mode_values.empty:

                cleaned_df[column] = cleaned_df[column].fillna(
                    mode_values.iloc[0]
                )

        elif method == "remove_duplicates":

            cleaned_df = cleaned_df.drop_duplicates().copy()

        elif method == "standardize_text":

            cleaned_df[column] = standardize_text(
                cleaned_df[column]
            )

        elif method == "convert_invalid_dates":

            cleaned_df[column] = pd.to_datetime(
                cleaned_df[column],
                errors="coerce"
            )

    return cleaned_df


# =====================================================
# 8. ADVANCED DATA VALIDATION
# =====================================================

def validate_dataset(df):

    validated_df = df.copy()

    REVIEW_STATUS = "Manual Review Required"

    validated_df["Review_Status"] = "Valid"
    validated_df["Date_Review_Status"] = "Valid"

    issues = []

    # -----------------------------------------------
    # NEGATIVE QUANTITY
    # -----------------------------------------------

    if "Quantity" in validated_df.columns:

        quantity = pd.to_numeric(
            validated_df["Quantity"],
            errors="coerce"
        )

        negative_quantity = quantity < 0

        validated_df.loc[
            negative_quantity,
            "Review_Status"
        ] = REVIEW_STATUS

        if negative_quantity.sum() > 0:

            issues.append({
                "Issue": "Negative Quantity",
                "Column": "Quantity",
                "Count": int(negative_quantity.sum())
            })

    # -----------------------------------------------
    # NEGATIVE UNIT PRICE
    # -----------------------------------------------

    if "Unit_Price" in validated_df.columns:

        unit_price = pd.to_numeric(
            validated_df["Unit_Price"],
            errors="coerce"
        )

        negative_price = unit_price < 0

        validated_df.loc[
            negative_price,
            "Review_Status"
        ] = REVIEW_STATUS

        if negative_price.sum() > 0:

            issues.append({
                "Issue": "Negative Unit Price",
                "Column": "Unit_Price",
                "Count": int(negative_price.sum())
            })

    # -----------------------------------------------
    # TOTAL SALES VALIDATION
    # -----------------------------------------------

    required_columns = [
        "Quantity",
        "Unit_Price",
        "Total_Sales"
    ]

    if all(
        col in validated_df.columns
        for col in required_columns
    ):

        quantity = pd.to_numeric(
            validated_df["Quantity"],
            errors="coerce"
        )

        price = pd.to_numeric(
            validated_df["Unit_Price"],
            errors="coerce"
        )

        total_sales = pd.to_numeric(
            validated_df["Total_Sales"],
            errors="coerce"
        )

        valid_sales = (
            quantity.notna()
            & price.notna()
            & total_sales.notna()
        )

        expected_sales = quantity * price

        mismatch = (
            valid_sales
            & (
                (total_sales - expected_sales).abs()
                > 0.000001
            )
        )

        validated_df.loc[
            mismatch,
            "Review_Status"
        ] = REVIEW_STATUS

        if mismatch.sum() > 0:

            issues.append({
                "Issue": "Total Sales Mismatch",
                "Column": "Total_Sales",
                "Count": int(mismatch.sum())
            })

    # -----------------------------------------------
    # INVALID AND MISSING DATES
    # -----------------------------------------------

    if "Order_Date" in validated_df.columns:

        original_dates = validated_df["Order_Date"]

        converted_dates = pd.to_datetime(
            original_dates,
            errors="coerce"
        )

        invalid_dates = (
            original_dates.notna()
            & converted_dates.isna()
        )

        missing_dates = original_dates.isna()

        date_review_mask = (
            invalid_dates | missing_dates
        )

        validated_df["Order_Date"] = converted_dates

        validated_df.loc[
            date_review_mask,
            "Date_Review_Status"
        ] = REVIEW_STATUS

        if invalid_dates.sum() > 0:

            issues.append({
                "Issue": "Invalid Dates",
                "Column": "Order_Date",
                "Count": int(invalid_dates.sum())
            })

        if missing_dates.sum() > 0:

            issues.append({
                "Issue": "Missing Dates",
                "Column": "Order_Date",
                "Count": int(missing_dates.sum())
            })

    # -----------------------------------------------
    # GENERATE VALIDATION REPORT
    # -----------------------------------------------

    report_df = pd.DataFrame(
        issues,
        columns=["Issue", "Column", "Count"]
    )

    return validated_df, report_df
