import streamlit as st
from sqlalchemy import text

# -----------------------------------------------------------------------------
# Database Setup
# -----------------------------------------------------------------------------
# This creates a connection. locally it uses sqlite. 
# For deployment, you would set 'connection_string' in .streamlit/secrets.toml
conn = st.connection("default", type="sql", url="sqlite:///quiz_app.db")

def init_db():
    with conn.session as s:
        s.execute(text("""
            CREATE TABLE IF NOT EXISTS questions (
                id INTEGER PRIMARY KEY,
                question_text TEXT,
                option_a TEXT,
                option_b TEXT,
                option_c TEXT,
                option_d TEXT,
                correct_option TEXT
            );
        """))
        s.commit()

# Initialize DB on first run
init_db()

# -----------------------------------------------------------------------------
# Session State Management
# -----------------------------------------------------------------------------
if 'user_role' not in st.session_state:
    st.session_state.user_role = None

def logout():
    st.session_state.user_role = None
    st.rerun()

# -----------------------------------------------------------------------------
# Teacher Interface
# -----------------------------------------------------------------------------
def teacher_page():
    st.header("👨‍🏫 Teacher Dashboard")
    st.write("Create a new multiple choice question.")

    with st.form("add_question_form"):
        q_text = st.text_area("Question Text")
        col1, col2 = st.columns(2)
        with col1:
            opt_a = st.text_input("Option A")
            opt_b = st.text_input("Option B")
        with col2:
            opt_c = st.text_input("Option C")
            opt_d = st.text_input("Option D")
        
        correct = st.selectbox("Correct Option", ["A", "B", "C", "D"])
        
        submitted = st.form_submit_button("Add Question")
        
        if submitted:
            if q_text and opt_a and opt_b and opt_c and opt_d:
                with conn.session as s:
                    s.execute(
                        text("INSERT INTO questions (question_text, option_a, option_b, option_c, option_d, correct_option) VALUES (:q, :oa, :ob, :oc, :od, :co)"),
                        params={"q": q_text, "oa": opt_a, "ob": opt_b, "oc": opt_c, "od": opt_d, "co": correct}
                    )
                    s.commit()
                st.success("Question added successfully!")
            else:
                st.error("Please fill in all fields.")

    st.divider()
    st.subheader("Existing Questions")
    
    # View existing data
    df = conn.query("SELECT * FROM questions", ttl=0)
    st.dataframe(df)

# -----------------------------------------------------------------------------
# Student Interface
# -----------------------------------------------------------------------------
def student_page():
    st.header("🎓 Student Dashboard")
    
    # Fetch all questions
    df = conn.query("SELECT * FROM questions", ttl=0)
    
    if df.empty:
        st.info("No questions available yet. Please ask your teacher to add some!")
        return

    with st.form("quiz_form"):
        answers = {}
        for index, row in df.iterrows():
            st.write(f"**Q{index+1}: {row['question_text']}**")
            options = {
                "A": row['option_a'],
                "B": row['option_b'],
                "C": row['option_c'],
                "D": row['option_d']
            }
            # Create radio buttons for options
            answers[row['id']] = st.radio(
                f"Select answer for Q{index+1}",
                options.keys(),
                format_func=lambda x: f"{x}: {options[x]}",
                key=f"q_{row['id']}"
            )
            st.divider()
            
        submitted = st.form_submit_button("Submit Quiz")
        
        if submitted:
            score = 0
            total = len(df)
            
            for index, row in df.iterrows():
                user_choice = answers[row['id']]
                if user_choice == row['correct_option']:
                    score += 1
            
            st.balloons()
            st.success(f"You scored {score} out of {total}!")
            if score == total:
                st.write("🌟 Perfect Score!")

# -----------------------------------------------------------------------------
# Main App Logic (Auth & Navigation)
# -----------------------------------------------------------------------------
st.title("📚 Streamlit EdTech Platform")

if not st.session_state.user_role:
    st.write("Please log in to continue.")
    
    col1, col2 = st.columns(2)
    with col1:
        if st.button("Log in as Teacher 👨‍🏫", use_container_width=True):
            st.session_state.user_role = "Teacher"
            st.rerun()
    with col2:
        if st.button("Log in as Student 🎓", use_container_width=True):
            st.session_state.user_role = "Student"
            st.rerun()

else:
    # Sidebar for logout
    with st.sidebar:
        st.write(f"Logged in as: **{st.session_state.user_role}**")
        if st.button("Logout"):
            logout()

    # Route to correct page
    if st.session_state.user_role == "Teacher":
        teacher_page()
    elif st.session_state.user_role == "Student":
        student_page()