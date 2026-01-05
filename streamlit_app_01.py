import streamlit as st
import pandas as pd
from streamlit_gsheets import GSheetsConnection
import os

st.set_page_config(page_title="🎟️ Event Management System", layout="wide")


# --- CONNECTIONS ---
# We initialize the connection using the URL from secrets
conn = st.connection("gsheets", type=GSheetsConnection)


def load_all_data():
    try:
        # ttl=0 is vital for 10+ users to see real-time updates
        tickets_df = conn.read(worksheet="tickets", ttl=0)
        menu_df = conn.read(worksheet="menu", ttl=0)

        # Validation to ensure we actually got data
        if tickets_df.empty or menu_df.empty:
            st.error("Connected to sheet, but no data was found.")
            st.stop()

        # Clean TicketID (ensure 4 digits like 0901)
        tickets_df['TicketID'] = tickets_df['TicketID'].astype(str).apply(lambda x: x.split('.')[0].zfill(4))

        # Ensure boolean types for Streamlit checkboxes/logic
        tickets_df['Sold'] = tickets_df['Sold'].fillna(False).astype(bool)
        tickets_df['Visited'] = tickets_df['Visited'].fillna(False).astype(bool)
        tickets_df['Visitor_Seats'] = pd.to_numeric(tickets_df['Visitor_Seats'], errors='coerce').fillna(0).astype(int)

        return tickets_df, menu_df
    except Exception as e:
        st.error(f"Failed to connect to Google Sheets: {e}")
        st.info("Check if the Sheet names are exactly 'tickets' and 'menu' (case sensitive).")
        st.stop()


def save_to_gsheets(tickets_df, menu_df=None):
    """Update the Google Sheet"""
    conn.update(worksheet="tickets", data=tickets_df)
    if menu_df is not None:
        conn.update(worksheet="menu", data=menu_df)
    st.cache_data.clear()


def custom_sort(df):
    if 'Seq' not in df.columns: return df
    return df.assign(sort_key=df['Seq'].apply(lambda x: 10 if x == 0 or x == '0' else int(x))).sort_values(
        'sort_key').drop(columns='sort_key')


# Initial Load
tickets, menu = load_all_data()

# --- SIDEBAR ---
with st.sidebar:
    st.header("Admin Settings")
    if st.button("🔄 Refresh Data"):
        st.rerun()

    admin_pass = st.text_input("Reset Password", type="password")
    if st.button("🚨 Reset Database"):
        if admin_pass == "admin123":
            # Logical reset (keeps structure, clears sales)
            tickets['Sold'] = False
            tickets['Visited'] = False
            tickets['Customer'] = ""
            tickets['Visitor_Seats'] = 0
            tickets['Timestamp'] = None
            save_to_gsheets(tickets)
            st.rerun()

t1, t2, t3, t4 = st.tabs(["📊 Dashboard", "💰 Sales", "🚶 Visitors", "⚙️ Edit Menu"])

# 1. DASHBOARD (Matches Image 2 format)
with t1:
    st.subheader("Inventory & Visitor Analytics")
    df = tickets.copy()

    summary = df.groupby(['Seq', 'Type', 'Category', 'Admit']).agg(
        Total_Tickets=('TicketID', 'count'),
        Tickets_Sold=('Sold', 'sum'),
        Total_Visitors=('Visitor_Seats', 'sum')
    ).reset_index()

    summary['Total_Seats'] = summary['Total_Tickets'] * summary['Admit']
    summary['Seats_sold'] = summary['Tickets_Sold'] * summary['Admit']
    summary['Balance_Tickets'] = summary['Total_Tickets'] - summary['Tickets_Sold']
    summary['Balance_Seats'] = summary['Total_Seats'] - summary['Seats_sold']
    summary['Balance_Visitors'] = summary['Seats_sold'] - summary['Total_Visitors']

    column_order = ['Seq', 'Type', 'Category', 'Admit', 'Total_Tickets', 'Tickets_Sold',
                    'Total_Seats', 'Seats_sold', 'Total_Visitors', 'Balance_Tickets',
                    'Balance_Seats', 'Balance_Visitors']

    summary = custom_sort(summary[column_order])

    totals = pd.DataFrame([summary.select_dtypes(include='number').sum()])
    totals['Seq'] = 'Total'
    summary_final = pd.concat([summary, totals], ignore_index=True).fillna('')

    st.dataframe(summary_final, hide_index=True, use_container_width=True)

# 2. SALES (Includes Bulk Upload)
with t2:
    st.subheader("Sales Management")
    col_in, col_out = st.columns([1, 1.2])

    with col_in:
        sale_tab = st.radio("Method", ["Manual", "Bulk Upload", "Reverse"], horizontal=True)

        if sale_tab == "Manual":
            s_type = st.radio("Type", ["Public", "Guest"], horizontal=True)
            s_cat = st.selectbox("Category", menu[menu['Type'] == s_type]['Category'])
            avail = tickets[(tickets['Type'] == s_type) & (tickets['Category'] == s_cat) & (~tickets['Sold'])][
                'TicketID'].tolist()

            if avail:
                with st.form("sale_form"):
                    tid = st.selectbox("Ticket ID", avail)
                    cust = st.text_input("Customer Name")
                    if st.form_submit_button("Confirm Sale"):
                        idx = tickets.index[tickets['TicketID'] == tid][0]
                        tickets.at[idx, 'Sold'] = True
                        tickets.at[idx, 'Customer'] = cust
                        tickets.at[idx, 'Timestamp'] = str(pd.Timestamp.now())
                        save_to_gsheets(tickets)
                        st.success(f"Sold {tid}!")
                        st.rerun()

        elif sale_tab == "Bulk Upload":
            uploaded_file = st.file_uploader("Upload Excel (Columns: TicketID, CustomerName)", type=["xlsx"])
            if uploaded_file and st.button("Process Bulk Sale"):
                up_df = pd.read_excel(uploaded_file)
                up_df['TicketID'] = up_df['TicketID'].astype(str).str.zfill(4)
                for _, row in up_df.iterrows():
                    match = tickets[(tickets['TicketID'] == row['TicketID']) & (~tickets['Sold'])]
                    if not match.empty:
                        idx = match.index[0]
                        tickets.at[idx, 'Sold'] = True
                        tickets.at[idx, 'Customer'] = row['CustomerName']
                        tickets.at[idx, 'Timestamp'] = str(pd.Timestamp.now())
                save_to_gsheets(tickets)
                st.rerun()

    with col_out:
        st.write("Recent Sales")
        st.dataframe(
            tickets[tickets['Sold']].sort_values('Timestamp', ascending=False)[['TicketID', 'Category', 'Customer']],
            hide_index=True)

# 3. VISITORS
with t3:
    v_in, v_out = st.columns([1, 1.2])
    with v_in:
        v_type = st.radio("Type", ["Public", "Guest"], key="v_type", horizontal=True)
        v_cat = st.selectbox("Category", menu[menu['Type'] == v_type]['Category'], key="v_cat")
        elig = tickets[
            (tickets['Type'] == v_type) & (tickets['Category'] == v_cat) & (tickets['Sold']) & (~tickets['Visited'])][
            'TicketID'].tolist()

        if elig:
            with st.form("checkin"):
                tid = st.selectbox("Ticket ID", elig)
                max_v = int(tickets[tickets['TicketID'] == tid]['Admit'].values[0])
                v_count = st.number_input("Visitors", 1, max_v, max_v)
                if st.form_submit_button("Confirm Entry"):
                    idx = tickets.index[tickets['TicketID'] == tid][0]
                    tickets.at[idx, 'Visited'] = True
                    tickets.at[idx, 'Visitor_Seats'] = v_count
                    tickets.at[idx, 'Timestamp'] = str(pd.Timestamp.now())
                    save_to_gsheets(tickets)
                    st.rerun()

# 4. EDIT MENU (Matches Image 1 format)
with t4:
    st.subheader("Menu & Series Configuration")
    menu_display = custom_sort(menu.copy())
    edited_menu = st.data_editor(menu_display, hide_index=True, use_container_width=True)
    if st.button("Update Google Sheet Menu"):
        save_to_gsheets(tickets, edited_menu)
        st.success("Menu Synchronized!")