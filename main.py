import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px

# --- PAGE CONFIG ---
st.set_page_config(page_title="Warehouse Command Center", layout="wide")

@st.cache_data
def load_and_clean_data():
    df = pd.read_parquet("stage2_eval_forecasts.parquet")
    df['dt'] = pd.to_datetime(df['dt'])
    
    # RENAME DICTIONARY (Manager-Friendly)
    rename_dict = {
        'in_stock': 'Availability_Status', # 1=Available, 0=Empty
        'recovered_demand': 'Actual_Market_Demand',
        'sale_amount': 'Recorded_Sales'
    }
    
    # Map h1-h7 to Day 1 - Day 7
    for i in range(1, 8):
        if f'lgb_h{i}' in df.columns:
            rename_dict[f'lgb_h{i}'] = f'Forecast_Day_{i}'
    
    return df.rename(columns=rename_dict)

try:
    df = load_and_clean_data()
except Exception as e:
    st.error(f"❌ Error loading data: {e}")
    st.stop()

# --- SIDEBAR FILTERS ---
st.sidebar.header("🕹️ Control Panel")
selected_store = st.sidebar.selectbox("Select Store Location", sorted(df['store_id'].unique()))
store_df = df[df['store_id'] == selected_store]

available_cats = sorted(store_df['first_category_id'].unique())
selected_cat = st.sidebar.selectbox("Select Department (Category)", available_cats)
view_df = store_df[store_df['first_category_id'] == selected_cat]

# --- SIMULATOR ---
st.sidebar.divider()
st.sidebar.subheader("⛈️ Weather & Promo Simulator")
rain_slider = st.sidebar.slider("Simulated Rainfall (mm)", 0, 50, 0)
promo_toggle = st.sidebar.toggle("Simulate Store-wide Promotion")

# --- HEADER ---
st.title("📦 Warehouse Operational Command Center")
st.subheader(f"Store: {selected_store} | Department: {selected_cat}")

# --- 1. LOST SALES AUDIT ---
if 'Recorded_Sales' in view_df.columns and 'Actual_Market_Demand' in view_df.columns:
    st.header("🔍 1. Lost Sales Audit (The 'Ghost Sales' Tracker)")
    col1, col2 = st.columns([2, 1])
    with col1:
        view_df['Lost_Units'] = (view_df['Actual_Market_Demand'] - view_df['Recorded_Sales']).clip(lower=0)
        history_fig = px.area(view_df.groupby('dt')['Lost_Units'].sum().reset_index(), 
                             x='dt', y='Lost_Units', title="Unmet Demand (Stockout Impact)")
        st.plotly_chart(history_fig, use_container_width=True)
    with col2:
        st.metric("Total Lost Sales Potential", f"{int(view_df['Lost_Units'].sum())} Units")
        st.info("💡 This is the demand we missed because the `Availability_Status` was 0.")

# --- 2. 7-DAY DEMAND HEATMAP ---
st.header("📈 2. 7-Day Forward Forecast")
forecast_cols = [c for c in view_df.columns if "Forecast_Day_" in c]

if forecast_cols:
    sim_multiplier = 1.0 + (rain_slider * 0.02) + (0.3 if promo_toggle else 0)
    
    # SECTION: Surge Alerts (3x higher than average)
    inventory_df = view_df.sort_values('dt').groupby('product_id').last().reset_index()
    inventory_df['Avg_7Day_Demand'] = inventory_df[forecast_cols].mean(axis=1) * sim_multiplier
    
    # Calculate historical average for Surge Alert
    hist_avg = view_df.groupby('product_id')['Actual_Market_Demand'].mean().reset_index(name='Baseline')
    inventory_df = inventory_df.merge(hist_avg, on='product_id')
    inventory_df['Is_Surging'] = inventory_df['Avg_7Day_Demand'] > (inventory_df['Baseline'] * 3)

    # Heatmap
    heatmap_data = inventory_df.set_index('product_id')[forecast_cols].head(20) * sim_multiplier
    fig_heat = px.imshow(heatmap_data, color_continuous_scale='YlOrRd', title="Demand Intensity for Next 7 Days")
    st.plotly_chart(fig_heat, use_container_width=True)

    # --- 3. REPLENISHMENT PRIORITY (NEW LOGIC) ---
    st.header("🚨 3. Replenishment Priority List")
    st.write("Prioritizing items that are either empty or facing massive predicted demand.")

    def get_priority(row):
        if row['Availability_Status'] == 0: return "🔴 CRITICAL: REFILL NOW"
        if row['Is_Surging']: return "🟡 WARNING: SURGE EXPECTED"
        if row['Avg_7Day_Demand'] > 5: return "🔵 MONITOR: HIGH VOLUME"
        return "🟢 STABLE"

    inventory_df['Priority_Status'] = inventory_df.apply(get_priority, axis=1)

    # Rename columns for manager view
    display_df = inventory_df[['product_id', 'Availability_Status', 'Avg_7Day_Demand', 'Priority_Status']]
    display_df['Current_State'] = display_df['Availability_Status'].map({1: "In Stock", 0: "OUT OF STOCK"})
    
    st.dataframe(display_df[['product_id', 'Current_State', 'Avg_7Day_Demand', 'Priority_Status']]
                 .sort_values(by=['Current_State', 'Avg_7Day_Demand'], ascending=[True, False]), 
                 use_container_width=True, hide_index=True)

    # --- 4. SMART REORDER LIST ---
    st.header("📑 4. Smart Order Generation")
    # We order based on total 7-day predicted volume
    inventory_df['Order_Quantity'] = (inventory_df[forecast_cols].sum(axis=1) * sim_multiplier).round(0)
    
    csv_data = inventory_df[inventory_df['Order_Quantity'] > 0][['product_id', 'Order_Quantity', 'Priority_Status']]
    st.download_button("📥 Download Smart Order CSV", data=csv_data.to_csv(index=False).encode('utf-8'), 
                      file_name="replenishment_list.csv", mime='text/csv')

st.caption("FreshRetailNet Framework | Binary Stock Logic Implemented")