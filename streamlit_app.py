import streamlit as st
import re
import json
import requests
from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled

# -----------------------------------------------------------------
# 1. PARENT CONFIGURATION (EDIT THESE VALUES)
# -----------------------------------------------------------------

# Paste the YouTube URL you want your son to watch
YOUTUBE_URL = "https://www.youtube.com/watch?v=X_crwFuPht4"

# Set the "Key Concept" you want the AI to focus on
KEY_CONCEPT = "The Hydraulic Analogy (water vs. electricity)"

# Set your child's name
CHILD_NAME = "My Son"

# -----------------------------------------------------------------
# 2. API Configuration
# -----------------------------------------------------------------

# Get the Hugging Face API token from secrets
HF_API_TOKEN = st.secrets.get("huggingface", {}).get("HF_API_TOKEN")

# This is the free AI model we will use
HF_MODEL_URL = "https://api-inference.huggingface.co/models/mistralai/Mistral-7B-Instruct-v0.2"

# -----------------------------------------------------------------
# 3. Page Configuration
# -----------------------------------------------------------------
st.set_page_config(
    page_title="Watch, Learn, & Win",
    page_icon="🧠",
    layout="wide"
)

# -----------------------------------------------------------------
# 4. YouTube & AI Functions
# -----------------------------------------------------------------

def extract_video_id(url):
    """Extracts the YouTube video ID from various URL formats."""
    patterns = [
        r"(?:v=|\/)([0-9A-Za-z_-]{11}).*",
        r"youtu\.be\/([0-9A-Za-z_-]{11})"
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None

@st.cache_data(ttl=3600)  # Cache transcript for 1 hour
def get_video_details(video_id):
    """Fetches and formats the transcript and title for a given video ID."""
    try:
        transcript_list = YouTubeTranscriptApi.get_transcript(video_id)
        transcript = " ".join([d['text'] for d in transcript_list])
        
        try:
            title = YouTubeTranscriptApi.list_transcripts(video_id).video_title
        except Exception:
            title = "Untitled YouTube Video"
            
        return transcript, title, None
    except TranscriptsDisabled:
        return None, None, f"Transcripts are disabled for this video."
    except Exception as e:
        return None, None, f"Failed to get transcript: {e}"

def parse_ai_response(response_text):
    """Extracts the JSON list from the AI's response."""
    try:
        start = response_text.find('[')
        end = response_text.rfind(']')
        if start != -1 and end != -1 and end > start:
            json_string = response_text[start:end+1]
            questions = json.loads(json_string)
            return questions
        else:
            return None
    except json.JSONDecodeError:
        return None

@st.cache_data(ttl=600) # Cache questions for 10 minutes
def generate_questions_from_ai(transcript, key_concept):
    """Generates 10 complex quiz questions using the Hugging Face API."""
    
    if not HF_API_TOKEN:
        return None, "Hugging Face API Token is not set in secrets.toml."

    prompt = f"""
    [INST] You are an expert educator. Your goal is to create a 10-question quiz that tests for *comprehension*.
    You will be given a video transcript and a "Key Concept."
    Your quiz must focus *only* on the Key Concept.
    You MUST respond with *only* a single, valid JSON list of 10 question blocks. Do not add any text before or after the list.

    RULES FOR EACH BLOCK:
    1.  **"question"**: The primary multiple-choice question about the Key Concept.
    2.  **"options"**: 4 potential answers.
    3.  **"answer"**: The *exact text* of the correct option.
    4.  **"explanation"**: A 1-2 sentence explanation of *why* the answer is correct.
    5.  **"secondary_question"**: A *follow-up* True/False question if the user gets the first one wrong.
    6.  **"secondary_options"**: ["True", "False"].
    7.  **"secondary_answer"**: The *exact text* of the correct secondary option.
    8.  **"secondary_explanation"**: A brief explanation for the secondary question's answer.

    EXAMPLE JSON FORMAT:
    [
      {{
        "question": "Based on the hydraulic analogy, what does 'Voltage' represent?",
        "options": ["The speed of the water", "The height of the water", "The width of the pipe", "The water temperature"],
        "answer": "The height of the water",
        "explanation": "Voltage is a 'potential,' like gravitational potential.",
        "secondary_question": "True or False: In this analogy, a wider pipe would mean *less* resistance.",
        "secondary_options": ["True", "False"],
        "secondary_answer": "True",
        "secondary_explanation": "A wider pipe allows more water to flow easily (lower resistance)."
      }}
    ]

    Now, generate the 10 questions based on this transcript and concept.
    TRANSCRIPT: "{transcript[:3000]}..." 
    KEY CONCEPT: "{key_concept}"
    [/INST]
    """
    
    headers = {"Authorization": f"Bearer {HF_API_TOKEN}"}
    payload = {
        "inputs": prompt,
        "parameters": { "max_new_tokens": 2048, "temperature": 0.7, "return_full_text": False }
    }
    
    try:
        response = requests.post(HF_MODEL_URL, headers=headers, json=payload, timeout=60)
        
        if response.status_code != 200:
            return None, f"AI generation failed: {response.status_code} - {response.text}"
        
        response_data = response.json()
        
        if isinstance(response_data, list):
            generated_text = response_data[0].get('generated_text', '')
        elif isinstance(response_data, dict):
            generated_text = response_data.get('generated_text', '')
        else:
            return None, "AI returned an unknown response format."

        questions = parse_ai_response(generated_text)
        
        if questions and isinstance(questions, list) and len(questions) > 0 and "secondary_question" in questions[0]:
            return questions[:10], None 
        else:
            st.error(f"Failed to parse JSON from AI. Raw text: {generated_text}")
            return None, "AI generated an invalid question format. The model might be loading. Please try again in a moment."
            
    except requests.exceptions.RequestException as e:
        return None, f"AI generation failed: {e}"

# -----------------------------------------------------------------
# 5. Main Quiz View
# -----------------------------------------------------------------

def initialize_quiz_state():
    """Sets up the session state for a new quiz."""
    st.session_state.quiz_started = True
    st.session_state.quiz_finished = False
    st.session_state.q_index = 0
    st.session_state.score = 0.0
    st.session_state.stage = 'primary'
    st.session_state.last_primary_correct = None
    st.session_state.last_secondary_correct = None
    st.session_state.current_explanation = ""
    st.session_state.current_secondary_explanation = ""

def run_quiz_view():
    st.title("🧠 Watch, Learn, & Win 🏆")
    
    if not HF_API_TOKEN:
        st.error("App is missing its AI Key. Please tell your parent!")
        st.stop()
    
    video_id = extract_video_id(YOUTUBE_URL)
    
    if not video_id:
        st.error("The YouTube URL set by your parent is invalid.")
        st.stop()

    # Get video title from the cached function
    _, video_title, error = get_video_details(video_id)
    if error:
        st.error(error)
        st.stop()
    
    st.header(f"Today's Challenge: {video_title}")
    st.subheader(f"Key Concept to Learn: {KEY_CONCEPT}")
    
    st.write(f"Welcome, {CHILD_NAME}!")

    # --- Show Video ---
    st.video(YOUTUBE_URL)

    # --- Initialize Session State ---
    if "quiz_started" not in st.session_state:
        st.session_state.quiz_started = False
    
    if st.button("Start Quiz", disabled=st.session_state.quiz_started):
        initialize_quiz_state()
        with st.spinner("Generating your unique comprehension quiz... This may take a moment."):
            transcript, _, error = get_video_details(video_id)
            if error:
                st.error(error)
                st.session_state.quiz_started = False
                st.stop()
            
            questions, error = generate_questions_from_ai(transcript, KEY_CONCEPT)
            if error:
                st.error(error)
                st.session_state.quiz_started = False
                st.stop()
            
            st.session_state.questions = questions
        st.rerun()

    # --- Main Quiz Logic (State Machine) ---
    if st.session_state.quiz_started and not st.session_state.get("quiz_finished", False):
        if "questions" not in st.session_state or not st.session_state.questions:
            st.error("Quiz questions not loaded. Please restart.")
            st.stop()

        q_list = st.session_state.questions
        q_index = st.session_state.q_index
        
        if q_index >= len(q_list):
             st.session_state.quiz_finished = True
             st.rerun()

        q_data = q_list[q_index]
        stage = st.session_state.stage

        st.progress((q_index + 1) / len(q_list))
        st.subheader(f"Question {q_index + 1} of {len(q_list)} (Score: {st.session_state.score:.1f})")

        # --- STAGE 1: Primary Question ---
        if stage == 'primary':
            with st.form(key=f"primary_q_{q_index}"):
                st.write(f"**{q_data['question']}**")
                user_answer = st.radio("Select your answer:", options=q_data['options'], index=None)
                if st.form_submit_button("Submit Answer"):
                    if user_answer:
                        if user_answer == q_data['answer']:
                            st.session_state.score += 1.0
                            st.session_state.last_primary_correct = True
                            st.session_state.stage = 'next_q'
                        else:
                            st.session_state.last_primary_correct = False
                            st.session_state.stage = 'secondary'
                        st.session_state.current_explanation = q_data['explanation']
                        st.rerun()
                    else:
                        st.warning("Please select an answer.")

        # --- STAGE 2: Secondary (Redemption) Question ---
        elif stage == 'secondary':
            st.error("That was incorrect.")
            st.info(f"**Explanation:** {st.session_state.current_explanation}")
            st.write("---")
            st.write("**Here's a chance to recover half a point:**")
            
            with st.form(key=f"secondary_q_{q_index}"):
                st.write(f"**{q_data['secondary_question']}**")
                user_answer_sec = st.radio("Select your answer:", options=q_data['secondary_options'], index=None)
                if st.form_submit_button("Submit Follow-up"):
                    if user_answer_sec:
                        if user_answer_sec == q_data['secondary_answer']:
                            st.session_state.score += 0.5
                            st.session_state.last_secondary_correct = True
                        else:
                            st.session_state.last_secondary_correct = False
                        st.session_state.current_secondary_explanation = q_data['secondary_explanation']
                        st.session_state.stage = 'next_q'
                        st.rerun()
                    else:
                        st.warning("Please select an answer.")
        
        # --- STAGE 3: Feedback & Move to Next Question ---
        elif stage == 'next_q':
            if st.session_state.last_primary_correct:
                st.success("Correct! Great job!")
                st.info(f"**Explanation:** {st.session_state.current_explanation}")
            else:
                if st.session_state.last_secondary_correct:
                    st.success("Good recovery! You earned 0.5 points.")
                    st.info(f"**Explanation:** {st.session_state.current_secondary_explanation}")
                else:
                    st.error("That was also incorrect.")
                    st.info(f"**Explanation:** {st.session_state.current_secondary_explanation}")

            if st.button("Next Question", type="primary"):
                if q_index < len(q_list) - 1:
                    st.session_state.q_index += 1
                    st.session_state.stage = 'primary'
                    st.session_state.last_primary_correct = None
                    st.session_state.last_secondary_correct = None
                else:
                    st.session_state.quiz_finished = True
                st.rerun()

    # --- Quiz Results ---
    if st.session_state.get("quiz_finished", False):
        score = st.session_state.score
        
        # Calculate minutes
        if score == 10.0:
            minutes_won = 30
        elif score >= 8.0: # 8.0 to 9.5
            minutes_won = 20
        else:
            minutes_won = 0
            
        st.header(f"Quiz Complete! Final Score: {score:.1f} / 10")
        
        if minutes_won > 0:
            st.balloons()
            st.success(f"Congratulations! You've earned {minutes_won} minutes of screen time.")
        else:
            st.error("Sorry, you didn't score high enough to earn time. You can try again.")

        st.info("Please show this screen to your parent to claim your time!")
        st.button("Retake Quiz") # This button will restart the app

# -----------------------------------------------------------------
# 6. Main App
# -----------------------------------------------------------------
def main():
    run_quiz_view()

if __name__ == "__main__":
    main()
