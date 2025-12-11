import streamlit as st
import pandas as pd
import google.generativeai as genai
import json
from sqlalchemy import text

# -----------------------------------------------------------------------------
# Database Setup (NEON / POSTGRES)
# -----------------------------------------------------------------------------
conn = st.connection("default", type="sql")

def init_db():
    with conn.session as s:
        # 1. Papers Table
        s.execute(text("""
            CREATE TABLE IF NOT EXISTS question_papers (
                id SERIAL PRIMARY KEY,
                title TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """))
        
        # 2. Questions Table
        s.execute(text("""
            CREATE TABLE IF NOT EXISTS questions (
                id SERIAL PRIMARY KEY,
                paper_id INTEGER REFERENCES question_papers(id) ON DELETE CASCADE,
                question_text TEXT,
                option_a TEXT,
                option_b TEXT,
                option_c TEXT,
                option_d TEXT,
                correct_option TEXT
            );
        """))

        # 3. Results Table
        s.execute(text("""
            CREATE TABLE IF NOT EXISTS exam_results (
                id SERIAL PRIMARY KEY,
                paper_id INTEGER REFERENCES question_papers(id) ON DELETE CASCADE,
                student_name TEXT,
                score INTEGER,
                total_questions INTEGER,
                percentage FLOAT,
                submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """))
        s.commit()

try:
    init_db()
except Exception as e:
    st.error(f"DB Init Error: {e}")

# -----------------------------------------------------------------------------
# AI Logic (Gemini)
# -----------------------------------------------------------------------------
def parse_questions_with_gemini(raw_text):
    try:
        if "GOOGLE_API_KEY" not in st.secrets:
            st.error("Google API Key not found in secrets.")
            return None

        genai.configure(api_key=st.secrets["GOOGLE_API_KEY"])
        model = genai.GenerativeModel('gemini-2.5-flash-lite')

        prompt = f"""
        You are an expert educational content creator. Analyze the raw text and convert it into a Quiz JSON.
        
        Rules:
        1. Ignore website noise (menus, ads).
        2. Convert subjective questions into MCQs with 4 options.
        3. If no answer is provided, SOLVE IT yourself.
        4. Output strictly a JSON array of objects. 
        5. REQUIRED KEYS: "question_text", "option_a", "option_b", "option_c", "option_d", "correct_option" (A, B, C, or D).

        Input Text:
        {raw_text}
        """

        response = model.generate_content(prompt)
        clean_text = response.text.strip()
        
        if clean_text.startswith("```json"): clean_text = clean_text[7:]
        elif clean_text.startswith("```"): clean_text = clean_text[3:]
        if clean_text.endswith("```"): clean_text = clean_text[:-3]

        return json.loads(clean_text)

    except Exception as e:
        st.error(f"AI Error: {e}")
        return None

# -----------------------------------------------------------------------------
# Session & Auth
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
    
    main_tab1, main_tab2, main_tab3 = st.tabs(["📄 Manage Papers", "❓ Manage Questions", "📊 View Results"])

    # =========================================================================
    # TAB 1: MANAGE PAPERS
    # =========================================================================
    with main_tab1:
        p_tab1, p_tab2, p_tab3, p_tab4 = st.tabs(["✨ AI Create", "➕ Manual", "📂 Upload CSV", "✏️ Edit/Delete"])

        # AI Create
        with p_tab1:
            st.subheader("Generate Quiz from Text")
            with st.form("ai_create_form"):
                ai_title = st.text_input("Paper Title")
                raw_input = st.text_area("Paste Text (Website content, Notes, etc)", height=200)
                if st.form_submit_button("Generate Exam"):
                    with st.spinner("AI is working..."):
                        data = parse_questions_with_gemini(raw_input)
                        if data:
                            with conn.session as s:
                                res = s.execute(text("INSERT INTO question_papers (title) VALUES (:t) RETURNING id"), params={"t": ai_title})
                                new_id = res.scalar()
                                
                                # --- FIXED LOOP HERE ---
                                for q in data:
                                    # Use .get() to prevent KeyError if AI misses a field
                                    q_text = q.get('question_text', 'Question text missing')
                                    oa = q.get('option_a', '-')
                                    ob = q.get('option_b', '-')
                                    oc = q.get('option_c', '-')
                                    od = q.get('option_d', '-')
                                    # Fallback to "A" if correct_option is missing
                                    co = q.get('correct_option', 'A').strip().upper() 
                                    
                                    # Ensure CO is just one letter
                                    if len(co) > 1: co = co[0]

                                    s.execute(text("INSERT INTO questions (paper_id,question_text,option_a,option_b,option_c,option_d,correct_option) VALUES (:pid,:q,:oa,:ob,:oc,:od,:co)"),
                                        params={"pid": new_id, "q": q_text, "oa": oa, "ob": ob, "oc": oc, "od": od, "co": co})
                                # -----------------------
                                
                                s.commit()
                            st.success(f"Created '{ai_title}'!")

        # Manual Create
        with p_tab2:
            with st.form("manual_p"):
                t = st.text_input("Title")
                if st.form_submit_button("Create"):
                    with conn.session as s:
                        s.execute(text("INSERT INTO question_papers (title) VALUES (:t)"), params={"t": t})
                        s.commit()
                    st.success("Created!")
                    st.rerun()

        # CSV Upload
        with p_tab3:
            with st.form("csv_up"):
                t = st.text_input("Title")
                f = st.file_uploader("CSV", type=["csv"])
                if st.form_submit_button("Upload") and f:
                    try:
                        df = pd.read_csv(f)
                        with conn.session as s:
                            res = s.execute(text("INSERT INTO question_papers (title) VALUES (:t) RETURNING id"), params={"t": t})
                            nid = res.scalar()
                            for i, row in df.iterrows():
                                s.execute(text("INSERT INTO questions (paper_id,question_text,option_a,option_b,option_c,option_d,correct_option) VALUES (:pid,:q,:oa,:ob,:oc,:od,:co)"),
                                    params={"pid": nid, "q": row['question_text'], "oa": row['option_a'], "ob": row['option_b'], "oc": row['option_c'], "od": row['option_d'], "co": str(row['correct_option']).upper()})
                            s.commit()
                        st.success("Uploaded!")
                    except Exception as e: st.error(e)

        # Edit/Delete Papers
        with p_tab4:
            papers = conn.query("SELECT * FROM question_papers ORDER BY id DESC", ttl=0)
            if not papers.empty:
                for i, row in papers.iterrows():
                    with st.expander(f"📄 {row['title']}"):
                        with st.form(f"del_p_{row['id']}"):
                            check = st.checkbox("Delete?", key=f"d_{row['id']}")
                            if st.form_submit_button("Delete"):
                                if check:
                                    with conn.session as s:
                                        s.execute(text("DELETE FROM question_papers WHERE id=:id"), params={"id": row['id']})
                                        s.commit()
                                    st.success("Deleted!")
                                    st.rerun()

    # =========================================================================
    # TAB 2: MANAGE QUESTIONS
    # =========================================================================
    with main_tab2:
        papers_df = conn.query("SELECT * FROM question_papers ORDER BY id DESC", ttl=0)
        if not papers_df.empty:
            opts = {f"{r['title']}": int(r['id']) for i, r in papers_df.iterrows()}
            
            sel_label = st.selectbox("Select Paper:", list(opts.keys()))
            pid = opts[sel_label]
            
            t1, t2 = st.tabs(["Add", "Edit"])
            with t1:
                with st.form("add_q"):
                    q = st.text_area("Question")
                    c1,c2=st.columns(2)
                    oa, ob = c1.text_input("A"), c1.text_input("B")
                    oc, od = c2.text_input("C"), c2.text_input("D")
                    co = st.selectbox("Correct", ["A","B","C","D"])
                    if st.form_submit_button("Add"):
                        with conn.session as s:
                            s.execute(text("INSERT INTO questions (paper_id,question_text,option_a,option_b,option_c,option_d,correct_option) VALUES (:pid,:q,:oa,:ob,:oc,:od,:co)"),
                                params={"pid":pid,"q":q,"oa":oa,"ob":ob,"oc":oc,"od":od,"co":co})
                            s.commit()
                        st.success("Added!")
            
            with t2:
                qdf = conn.query("SELECT * FROM questions WHERE paper_id=:pid ORDER BY id", params={"pid":pid}, ttl=0)
                if not qdf.empty:
                    for i, r in qdf.iterrows():
                        with st.expander(f"Q: {r['question_text'][:40]}"):
                            with st.form(f"eq_{r['id']}"):
                                nq = st.text_area("Q", r['question_text'])
                                noa, nob = st.text_input("A", r['option_a']), st.text_input("B", r['option_b'])
                                noc, nod = st.text_input("C", r['option_c']), st.text_input("D", r['option_d'])
                                nco = st.selectbox("Cor", ["A","B","C","D"], index=["A","B","C","D"].index(r['correct_option']))
                                dchk = st.checkbox("Delete?")
                                if st.form_submit_button("Update"):
                                    with conn.session as s:
                                        if dchk:
                                            s.execute(text("DELETE FROM questions WHERE id=:id"), params={"id":r['id']})
                                        else:
                                            s.execute(text("UPDATE questions SET question_text=:q,option_a=:oa,option_b=:ob,option_c=:oc,option_d=:od,correct_option=:co WHERE id=:id"),
                                                params={"q":nq,"oa":noa,"ob":nob,"oc":noc,"od":nod,"co":nco,"id":r['id']})
                                        s.commit()
                                    st.rerun()

    # =========================================================================
    # TAB 3: VIEW RESULTS
    # =========================================================================
    with main_tab3:
        st.subheader("📊 Class Performance Analytics")
        
        papers_df = conn.query("SELECT * FROM question_papers ORDER BY id DESC", ttl=0)
        
        if papers_df.empty:
            st.info("No papers created yet.")
        else:
            opts = {f"{r['title']}": int(r['id']) for i, r in papers_df.iterrows()}
            
            sel_label = st.selectbox("Select Exam to View Results:", list(opts.keys()), key="res_sel")
            pid = opts[sel_label]
            
            res_df = conn.query("SELECT * FROM exam_results WHERE paper_id = :pid ORDER BY submitted_at DESC", params={"pid": pid}, ttl=0)
            
            if res_df.empty:
                st.info("No students have taken this exam yet.")
            else:
                avg_score = res_df['percentage'].mean()
                top_score = res_df['percentage'].max()
                total_students = len(res_df)
                
                c1, c2, c3 = st.columns(3)
                c1.metric("Total Attempts", total_students)
                c2.metric("Average Score", f"{avg_score:.1f}%")
                c3.metric("Top Score", f"{top_score:.1f}%")
                
                st.divider()
                st.bar_chart(res_df, x="student_name", y="percentage")
                st.write("### Detailed Results")
                st.dataframe(res_df[['student_name', 'score', 'total_questions', 'percentage', 'submitted_at']])

# -----------------------------------------------------------------------------
# Student Interface
# -----------------------------------------------------------------------------
def student_page():
    st.header("🎓 Student Dashboard")
    
    if "student_name" not in st.session_state:
        st.session_state.student_name = ""
        
    name_input = st.text_input("Enter your Full Name to start:", value=st.session_state.student_name)
    
    if name_input:
        st.session_state.student_name = name_input
        
        papers_df = conn.query("SELECT * FROM question_papers ORDER BY id DESC", ttl=0)
        if papers_df.empty:
            st.warning("No exams available.")
            return
        
        sel = st.selectbox("Choose Exam:", papers_df['title'])
        pid = int(papers_df[papers_df['title']==sel].iloc[0]['id'])
        
        qdf = conn.query("SELECT * FROM questions WHERE paper_id=:pid", params={"pid":pid}, ttl=0)
        if qdf.empty:
            st.info("This exam has no questions.")
            return

        st.divider()
        st.subheader(f"Attempting: {sel}")
        
        with st.form("exam_form"):
            ans = {}
            for i, r in qdf.iterrows():
                st.write(f"**{i+1}. {r['question_text']}**")
                ans[r['id']] = st.radio("Select Answer:", ["A","B","C","D"], format_func=lambda x: f"{x}: {r[f'option_{x.lower()}']}", key=f"q{r['id']}")
                st.divider()
            
            submitted = st.form_submit_button("Submit Exam")
            
            if submitted:
                score = 0
                total = len(qdf)
                for i, r in qdf.iterrows():
                    if r['id'] in ans and ans[r['id']] == r['correct_option']:
                        score += 1
                
                percentage = round((score/total)*100, 2)
                
                with conn.session as s:
                    s.execute(
                        text("""
                            INSERT INTO exam_results (paper_id, student_name, score, total_questions, percentage) 
                            VALUES (:pid, :name, :scr, :tot, :perc)
                        """),
                        params={
                            "pid": pid,
                            "name": st.session_state.student_name,
                            "scr": score,
                            "tot": total,
                            "perc": percentage
                        }
                    )
                    s.commit()
                
                if percentage == 100:
                    st.balloons()
                    st.success(f"🏆 Perfect! {score}/{total} (100%)")
                elif percentage >= 50:
                    st.success(f"✅ Pass! {score}/{total} ({percentage}%)")
                else:
                    st.error(f"❌ Score: {score}/{total} ({percentage}%)")
                
                st.info("Your result has been saved.")

# -----------------------------------------------------------------------------
# Main App Entry (PASSWORD PROTECTED)
# -----------------------------------------------------------------------------
st.title("📚 Cloud Quiz AI")

# --- PASSWORDS ---
TEACHER_PASS = "CuteBoy"
STUDENT_PASS = "StupidKid"
# -----------------

if not st.session_state.user_role:
    st.write("Please log in to continue.")
    
    login_tab1, login_tab2 = st.tabs(["👨‍🏫 Teacher Login", "🎓 Student Login"])
    
    with login_tab1:
        t_password = st.text_input("Teacher Password", type="password", key="t_pass")
        if st.button("Login as Teacher"):
            if t_password == TEACHER_PASS:
                st.session_state.user_role = "Teacher"
                st.rerun()
            else:
                st.error("Incorrect Password!")

    with login_tab2:
        s_password = st.text_input("Student Password", type="password", key="s_pass")
        if st.button("Login as Student"):
            if s_password == STUDENT_PASS:
                st.session_state.user_role = "Student"
                st.rerun()
            else:
                st.error("Incorrect Password!")

else:
    with st.sidebar:
        st.write(f"Logged in as: **{st.session_state.user_role}**")
        if st.button("Logout", type="primary"):
            logout()

    if st.session_state.user_role == "Teacher":
        teacher_page()
    elif st.session_state.user_role == "Student":
        student_page()
