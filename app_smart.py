
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
