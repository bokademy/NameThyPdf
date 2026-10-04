"""
NameThyPdf - Web UI
Streamlit application for organizing messy academic PDFs into a curated library.
"""

import os
import tempfile
import zipfile
import streamlit as st
import core_pipeline as pipeline

st.set_page_config(
    page_title="NameThyPdf",
    page_icon="📖",
    layout="centered"
)

# Retrieve Groq API Key from Streamlit Secrets or Environment Variables
GROQ_API_KEY = st.secrets.get("GROQ_API_KEY", os.getenv("GROQ_API_KEY"))

st.title("📖 NameThyPdf")
st.markdown("Bring sanity to messy PDF names.")

uploaded_files = st.file_uploader(
    "Select or drop PDF files to organize:",
    type=["pdf"],
    accept_multiple_files=True
)

if uploaded_files:
    st.write(f"**{len(uploaded_files)}** PDF files ready to process.")
    
    if st.button("Start Renaming & Organizing", type="primary"):
        progress_bar = st.progress(0)
        status_box = st.empty()

        with tempfile.TemporaryDirectory() as temp_dir:
            input_dir = os.path.join(temp_dir, "input")
            output_dir = os.path.join(temp_dir, "output")
            os.makedirs(pipeline.win_safe(input_dir), exist_ok=True)
            os.makedirs(pipeline.win_safe(output_dir), exist_ok=True)

            # Save uploaded files with path normalization and length guardrails
            for uploaded_file in uploaded_files:
                raw_name = uploaded_file.name.replace('’', "'").replace('‘', "'")
                base, ext = os.path.splitext(raw_name)
                safe_name = f"{base[:110]}{ext}" if len(base) > 110 else raw_name
                
                target_input_path = pipeline.win_safe(os.path.join(input_dir, safe_name))
                with open(target_input_path, "wb") as f:
                    f.write(uploaded_file.getbuffer())

            status_box.info("Resolving identifiers and extracting bibliographic metadata...")
            progress_bar.progress(25)

            # Execute pipeline with rate pacing and Groq credentials
            results = pipeline.run_pipeline(
                input_dir=input_dir, 
                output_dir=output_dir, 
                groq_key=GROQ_API_KEY
            )
            progress_bar.progress(80)

            # Packaging Output into a Single ZIP
            status_box.info("Packaging curated library and RIS records...")
            zip_path = os.path.join(temp_dir, "NameThyPdf_Curated_Library.zip")
            with zipfile.ZipFile(pipeline.win_safe(zip_path), "w", zipfile.ZIP_DEFLATED) as zipf:
                library_dir = os.path.join(output_dir, "Library")
                if os.path.exists(pipeline.win_safe(library_dir)):
                    for root, _, files in os.walk(library_dir):
                        for file in files:
                            full_p = os.path.join(root, file)
                            zipf.write(pipeline.win_safe(full_p), arcname=os.path.join("Library", file))

                ris_path = os.path.join(output_dir, "collection.ris")
                if os.path.exists(pipeline.win_safe(ris_path)):
                    zipf.write(pipeline.win_safe(ris_path), arcname="collection.ris")

            progress_bar.progress(100)
            status_box.success("Library curated successfully!")

            # Display Results Table
            st.subheader("Processing Log")
            log_data = []
            for success, name, detail in results:
                log_data.append({
                    "Status": "✅ Success" if success else "⚠ Quarantined",
                    "Target / File": name,
                    "Info / Type": detail
                })
            st.table(log_data)

            # Verification Disclaimer
            st.warning("⚠️ Notice: Automated metadata extraction is an aid, not a miracle. Always inspect your generated references.")

            # Download Button
            with open(pipeline.win_safe(zip_path), "rb") as f:
                st.download_button(
                    label="📥 Download Curated Library (ZIP)",
                    data=f,
                    file_name="NameThyPdf_Curated_Library.zip",
                    mime="application/zip"
                )